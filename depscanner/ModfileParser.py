from base64 import b64decode
from urllib.parse import urlparse, urljoin
import json
import re
import logging
import requests
import toml
import semver
from pkg_resources import parse_requirements as setuptools_parse_requirements

from collections import namedtuple

class DependencyInfo:
    def __init__(self, name: str=None, url: str=None, semver_string: str= None):
        self.name = name
        self.semver = semver_string
        self.url = url

class ModfileParser:
    """Class to parse the dependency files of the repositories"""

    def __init__(
        self,
        proxies: dict,
        headers: dict,
        logger: logging.Logger,
    ):
        self.proxies = proxies
        self.headers = headers
        self.logger = logger

    def get_and_parse_depfile(self, item) -> list[DependencyInfo]:
        """Wrapper for all the other parsing functions"""
        dep_file_name = item["name"]
        dependencies = []
        if re.match(".*requirements.txt$", dep_file_name):
            dependencies = self.get_and_parse_requirements(item)
        elif re.match("package.json$", dep_file_name):
            dependencies = self.get_and_parse_package_json(item)
        elif re.match(".*Pipfile$", dep_file_name):
            dependencies = self.get_and_parse_pipfile(item)
        elif re.match(".*poetry.toml$", dep_file_name):
            dependencies = self.get_and_parse_toml(item)
        elif re.match(".*Gemfile$", dep_file_name):
            dependencies = self.get_and_parse_gemfile(item)
        elif dep_file_name == "go.mod":
            dependencies = self.get_and_parse_gomod(item)
        else:
            self.logger.error(f"Unknown dependency file: {item['path']}")

        return dependencies

    # optionally, environment markers
    def _parse_requirement_line(self, req) -> DependencyInfo:
        """Parse a single requirement line into structured data.
        https://pip.pypa.io/en/stable/reference/requirement-specifiers/#overview
        A requirement specifier comes in two forms:
        1. name-based, which is composed of:
        * a package name (eg: requests)
        * optionally, a set of “extras” that serve to install optional dependencies (eg: security)
        * optionally, constraints to apply on the version of the package
        * optionally, environment markers
        2. URL-based, which is composed of:
        * a package name (eg: requests)
        * optionally, a set of “extras” that serve to install optional dependencies (eg: security)
        * a URL for the package
        """
        depinfo = DependencyInfo(
            name=req.name,
            semver_string="*",
            url=""
        ) 

        # Handle URL-based requirements
        if req.url:
            depinfo.url = req.url
            # If it's a VCS URL, try to extract semver requirement from fragment
            if "#" in req.url:
                depinfo.semver = req.url.split("#")[-1]
        # Handle version specifiers
        elif req.specs:
            # Convert specs list like [('>=', '1.0'), ('<=', '2.0')] to string
            semver_specs = []
            for operator, version in req.specs:
                semver_specs.append(f"{operator}{version}")
            depinfo.semver = ",".join(semver_specs)

        return depinfo

    def get_and_parse_requirements(self, item) -> list:
        """
        Parse requirements.txt file
        Handles:
        1. Name-based requirements:
           - package name (requests)
           - extras [security]
           - version constraints (>=1.0.0)
           - environment markers
        2. URL-based requirements:
           - VCS URLs (git+https://github.com/org/pkg.git@master#egg=pkg)
           - Direct download URLs (https://example.com/pkg.tar.gz)
        """
        dependencies = []
        self.logger.debug(f"Downloading contents of {item['name']} from {item['url']}")
        response = requests.get(
            item["url"],
            proxies=self.proxies,
            verify=False,
            headers=self.headers,
            timeout=10,
        )
        if response.status_code == 200:
            decoded_content = b64decode(response.json()["content"]).decode("utf-8")
            try:
                for req in setuptools_parse_requirements(decoded_content):
                    dependencies.append(self._parse_requirement_line(req))
            except Exception as e:
                self.logger.debug(f"Error parsing the file {item['name']}: {e}")
        return dependencies

    def get_and_parse_pipfile(self, item) -> list:
        """Parser for Pipfile"""
        return self.get_and_parse_toml(item=item)

    def get_and_parse_toml(self, item) -> list:
        """Pipfiles are just toml syntax"""

        dependencies = []
        self.logger.debug(f"Downloading contents of {item['name']} from {item['url']}")
        response = requests.get(
            item["url"],
            proxies=self.proxies,
            verify=False,
            headers=self.headers,
            timeout=10,
        )
        if response.status_code == 200:
            decoded_content = b64decode(response.json()["content"]).decode("utf-8")
            try:
                toml_content = toml.loads(decoded_content)

                for section in ("packages", "dev-packages"):
                    if section in toml_content:
                        for name, details in toml_content[section].items():
                            if isinstance(details, str):
                                semver_string = details
                                url = None
                            elif isinstance(details, dict):
                                semver_string = details.get("version", "*")
                                url = details.get("path") or details.get("git")
                            else:
                                continue

                            dependencies.append(
                                DependencyInfo(
                                    name=name,
                                    semver_string=semver_string,
                                    url=url
                                ) 
                            )
            except Exception as e:
                self.logger.error(f"Error parsing toml file {item['name']}: {e}")

        return dependencies

    def _is_semver(self, version: str) -> bool:
        """Returns true if the value of a dependency in a package.json looks like a version"""
        # Versions parsing for packages.json files can be hell, I'll just handle a few variations
        # https://docs.npmjs.com/cli/v11/configuring-npm/package-json#dependencies
        if ("||" in version):
            # Recursive call to _is_semver to validate each part of the OR. If all are semver, then this is ok to store as semver version
            return all([self._is_semver(v.strip()) for v in version.split("||")])
        elif ("-" in version):
            # Recursive call to _is_semver to validate each part of the OR. If all are semver, then this is ok to store as semver version
            return all([self._is_semver(v.strip()) for v in version.split("-")])
        elif ("," in version):
            # Recursive call to _is_semver to validate each part of the OR. If all are semver, then this is ok to store as semver version
            return all([self._is_semver(v.strip()) for v in version.split("-")])
        else:
            # Take into account the versions are specified as ^4.5.6 sometimes, this breaks semver package parsing
            nvalue = re.sub(r"[\^><=~]", "", version)
            try:
                semver.parse_version_info(nvalue)
                return True
            except Exception as e:
                self.logger.debug(
                    f"{version} (normalized as {nvalue}) does not seem to be a semver-compatible string: {e}"
                )
                return False

    def _is_package_local_path(self, value: str) -> bool:
        """Check if the value is a local path"""
        return value.startswith(("file:", "./", "~/", "../", "/", "workspace:"))

    def _is_package_npm_url(self, value: str) -> bool:
        """Check if the value is an npm URL"""
        return value.startswith("npm:")

    def _is_package_github_url(self, value: str) -> bool:
        """
        Check if value matches either:
        1. GitHub shorthand: "user/repo#commit-ish"
        2. Full URL: "protocol://hostname/path#commit-ish"
        """
        return (
            "github:" in value
            or re.match(r"^[\w-]+\/[\w-]+(?:#[\w\/-]+)?$", value) is not None
            or re.match(
                r"^(?:git\+)?(?:https?|git|ssh):\/\/(?:[\w-]+(?::\S+)?@)?(?:[\w\.-]+)(?::\d+)?[\/:][\w\/-]+(?:#[\w\/-]+)?$",
                value,
            )
            is not None
        )

    def _parse_github_dependency(self, value: str) -> tuple:
        """
        Handle both shorthand and full URLs:
        - "expressjs/express" -> ("https://github.com/expressjs/express", "main")
        - "mochajs/mocha#4727d357ea" -> ("https://github.com/mochajs/mocha", "4727d357ea")
        - "https://github.com/user/repo#branch" -> ("https://github.com/user/repo", "branch")
        - "git://github.com/user/repo.git#tag" -> ("https://github.com/user/repo", "tag")
        - "git+ssh://git@github.com:user/repo#v1.2.3" -> ("https://github.com/user/repo", "v1.2.3")
        """

        if "github:" in value:
            value = value.replace("github:", "")
            return (f"https://github.com/{value}", "main")

        # If it's a shorthand notation
        if re.match(r"^[\w-]+\/[\w-]+", value):
            parts = value.split("#", 1)
            repo = parts[0]
            version = parts[1] if len(parts) > 1 else "main"
            return (f"https://github.com/{repo}", version)

        # If it's a full URL
        url_match = re.match(
            r"^(?:git\+)?(?:https?|git|ssh):\/\/(?:[\w-]+(?::\S+)?@)?(?:[\w\.-]+)(?::\d+)?[\/:](?P<path>[\w\/-]+)(?:#(?P<version>[\w\/-]+))?",
            value,
        )
        if url_match:
            path = re.sub(r"\.git$", "", url_match.group("path"))
            version = url_match.group("version") or "main"
            return (f"https://github.com/{path}", version)

        return (value, "unknown")  # Fallback for unrecognized formats

    def _is_package_remote_tar_url(self, value: str) -> bool:
        """Check if the value is a remote tarball URL"""
        return value.endswith(".tgz") or value.endswith(".tar.gz")

    def get_and_parse_package_json(self, item) -> list:
        """
        Parser for package.json
        https://docs.npmjs.com/cli/v11/configuring-npm/package-json#dependencies
        TODO: Account for the cases where there is an internal link in the dependency, such as:
        * "@types/divi__object-renderer": "npm:divi-types-object-renderer@^1.0.8", (https://github.com/elegantthemes/d5-dev-tool/blob/main/package.json )
        * "@kbn/alerting-types": "link:src/platform/packages/shared/kbn-alerting-types", (https://github.com/elastic/kibana/blob/main/package.json)
        """
        dependencies = []

        self.logger.debug(f"Downloading contents of {item['name']} from {item['url']}")
        response = requests.get(
            item["url"],
            proxies=self.proxies,
            verify=False,
            headers=self.headers,
            timeout=10,
        )
        if response.status_code == 200:
            decoded_content = b64decode(response.json()["content"]).decode("utf-8")
            try:
                package_data = json.loads(decoded_content)
                for section in [
                    "dependencies",
                    "devDependencies",
                    "peerDependencies",
                    "optionalDependencies",
                ]:
                    if section in package_data:
                        for dependency_name, value in package_data[section].items():
                            semver_string = "latest"
                            dependency_url = ""
                            if value=="*":
                                semver_string = value
                            elif self._is_semver(value):
                                semver_string = value
                            elif self._is_package_npm_url(value):
                                dependency_url = value
                            elif self._is_package_github_url(value):
                                dependency_url, semver_string = (
                                    self._parse_github_dependency(value)
                                )
                            elif self._is_package_remote_tar_url(value):
                                dependency_url = value
                            elif self._is_package_local_path(value):
                                dependency_url = value
                                self.logger.debug(
                                    f"Package {dependency_name} with value {value} looks like a local path. Ignoring this one."
                                )
                                continue
                            else:
                                self.logger.warning(
                                    f"Unknown dependency value format: {value}"
                                )
                            dependencies.append(
                                DependencyInfo(
                                    name=dependency_name,
                                    semver_string=semver_string,
                                    url=dependency_url
                                ) 
                            )
            except Exception as e:
                self.logger.error(f"Error parsing json of file {item['name']}: {e}")
        return dependencies

    def get_and_parse_gomod(self, item) -> list:
        """Parses the go.mod file and try to find the modules following the same rules as described here: https://go.dev/ref/mod#vcs-find"""
        modules = []
        module_path = ""
        vcs_protos = ["https", "bzr+ssh", "git+ssh", "ssh", "svn-ssh"]
        vcs_qualifiers = [".bzr", ".fossil", ".git", ".hg", ".svn"]
        append_query = "?go-get=1"
        try:
            self.logger.debug(
                f"Downloading contents of {item['name']} from {item['url']}"
            )
            response = requests.get(
                item["url"],
                proxies=self.proxies,
                verify=False,
                headers=self.headers,
                timeout=10,
            )
            if response.status_code == 200:
                decoded_content = b64decode(response.json()["content"]).decode("utf-8")

                # Parse go.mod file to extract dependencies
                in_require_block = False
                for line in decoded_content.splitlines():
                    line = line.strip()
                    if line.startswith("require ("):
                        in_require_block = True
                        continue
                    if line.startswith(")"):
                        in_require_block = False
                        continue

                    # If we are within a require block or the line starts with the require keyword:
                    if ((re.match(r" v\d", line)) is not None) and (
                        in_require_block or line.startswith("require ")
                    ):
                        # Remove any trailining comments from the line
                        sline = line.split(" ")
                        # go.mod parts (1: path, 2: version)
                        path = sline[0]
                        semver_string = sline[1]
                        module_path = path

                        # If the module path has a VCS qualifier (one of .bzr, .fossil, .git, .hg, .svn) at the end of a path component, the go command will use everything up to that path qualifier as the repository URL.
                        # https://go.dev/ref/mod#vcs-find
                        present_vcs = set(
                            map(
                                lambda vcs: vcs if vcs in module_path else None,
                                vcs_qualifiers,
                            )
                        )
                        present_vcs.remove(None)
                        if len(present_vcs) > 0:
                            # Get the module url up tho the vcs part
                            vcs = present_vcs.pop()
                            self.logger.debug(
                                f"The module {module_path} of repository {item['name']} has the vcs {vcs}"
                            )
                            rec = re.compile(r"^(?P<url_vcs>.*" + vcs + r").*$")
                            m = re.match(rec, item["url"])
                            if m is not None:
                                module_path = m.groupdict()["url_vcs"]

                        # Separate the module path into its components https://go.dev/ref/mod#vcs-find
                        # Typically, a module path consists of a repository root path, a directory within the repository (usually empty), and a major version suffix (only for major version 2 or higher).
                        # This is a simplification of the process. I'm not going to try all the protocols, and default to https://
                        # Example returning a <meta> tag with the repo info:
                        # https://k8s.io/apimachinery?go-get=1
                        goimport_content = ""
                        if "://" not in module_path and not any(
                            map(lambda prot: prot in module_path, vcs_protos)
                        ):
                            module_path = "https://" + module_path

                        resp = requests.get(
                            urljoin(module_path, append_query),
                            proxies=self.proxies,
                            verify=False,
                            headers=self.headers,
                            timeout=10,
                        )
                        m = re.match(
                            r"<meta\s+name=\"go-import\"\s+content=[\"'](?P<goimport_content>.*)[\"']>",
                            resp.text,
                        )
                        repo_path = ""
                        root_path = ""
                        if m is not None:
                            goimport_content = m.groupdict()["goimport_content"]
                            gcp = goimport_content.split(" ")
                            root_path = gcp[0]
                            vcs = gcp[1]
                            repo_path = gcp[2]

                        modules.append(
                            DependencyInfo(
                                name=root_path,
                                semver_string=semver_string,
                                url=repo_path
                            )
                        )
        except Exception as e:
            self.logger.error(
                f"Error downloading and parsing go.mod file {item['name']}: {e}"
            )
        return modules

    def get_and_parse_gemfile(self, item) -> list:
        """
        Downloads the Gemfile and parses it to extract the dependencies
        Syntax of gemfiles: https://bundler.io/guides/gemfile.html
        """
        DEFAULT_SOURCE = "https://rubygems.org"
        # https://rubygems.org/gems/requests
        dependencies = []
        gem_name = ""
        semver_string = "*"
        gem_url = ""

        # TODO: To avoid retrieving the package information twice
        # Get from the database the package information if it exists
        # If it does not exist, then retrieve it from the URL

        version_regex = r"\"?(?P<gem_version>([~^><=]*\s*\d+\.\d+\.\d+(-\w+(\.\d+)?)?(\+\w+(\.\d+)?)?)|([~^><=]*\s*\d+\.\d+)|([~^><=]*\s*\d+))\"?"
        gem_name_regex = r"gem\s+[\"'](?P<gem_name>\w+)[\"']"
        gem_name_regex_compiled = re.compile(gem_name_regex)
        version_regex_compiled = re.compile(version_regex)

        self.logger.debug(f"Downloading contents of {item['name']} from {item['url']}")
        response = requests.get(
            item["url"],
            proxies=self.proxies,
            verify=False,
            headers=self.headers,
            timeout=10,
        )
        if response.status_code == 200:
            decoded_content = b64decode(response.json()["content"]).decode("utf-8")

            # Parse lines that start with 'gem'
            alternate_source_block = False
            for line in decoded_content.splitlines():
                line = line.strip()
                # Find the source if there is one e.g.
                # source 'http://rubygems.org'
                previous_source = source = DEFAULT_SOURCE
                msource = re.match(
                    r"source\s+['\"](?P<source_url>.*)['\"]\s+(?P<do_keyword>do)$", line
                )
                if msource is not None:
                    msg = msource.groupdict()
                    if "source_url" in msg:
                        source = msg["source_url"]
                    if "do_keyword" in msg:
                        # We are in a block with an alternative source, so we save the previous source to restore it back when we find the keyword
                        previous_source = source
                        source = msg["source_url"]
                        alternate_source_block = True

                # If we were inside an alternate source block and we find an "end", the block ends
                if re.match(r"^end$", line) is not None and alternate_source_block:
                    alternate_source_block = False
                    source = previous_source

                # Find the gems and their attributes
                # e.g.:
                # gem 'nokogiri', :git => 'https://github.com/tenderlove/nokogiri.git', :branch => '1.4'
                # gem 'rails', '5.0.0'
                # gem 'rack',  '>=1.0'
                # gem 'thin',  '~>1.1'
                if line.startswith("gem"):
                    # Remove all appended comments in this line
                    line = re.sub(r"#.*$", "", line).strip()
                    # Split by commas
                    parts = [l.strip() for l in line.split(",")]
                    for part in parts:
                        # The gem name is specified at the begining as "gem 'gemfile_name'"
                        m = gem_name_regex_compiled.match(part)
                        if m is not None:
                            gem_name = m.groupdict()["gem_name"]

                        # Check if this is the version of the gemfile, which is usually after the gem name
                        m = version_regex_compiled.match(part)
                        if m is not None:
                            semver_string = m.groupdict()["gem_version"]

                        # Alternate sources: for each gem its possible
                        # e.g.: gem 'my_gem', '1.0', :source => 'https://gems.example.com'
                        if ":source " in part:
                            source = (
                                part.split("=>")[-1]
                                .strip()
                                .replace("'", "")
                                .replace('"', "")
                            )

                        # There could be a local path:
                        # e.g.: :path => './vendor/extracted_library'
                        if ":path " in part or "path: " in part:
                            gem_path = (
                                part.split("=>")[-1]
                                .strip()
                                .replace("'", "")
                                .replace('"', "")
                            )
                            if len(gem_path) > 0:
                                # Ignore this gem, as its pulling it from the local hard drive
                                continue

                        # This part is an attribute like :git => https://xxx.com/bla. E.g.:
                        # gem 'measurebation', :git => 'git://github.com/tijn/measurebation.git'
                        m = None
                        git_url = None
                        if "git: " in part:
                            m = re.match(
                                r"^:git\s+=>\s+['\"](?P<git_url>.*)['\"]$", part
                            )
                        if ":git" in part and "=>" in part:
                            m = re.match(r"^git:\s+['\"](?P<git_url>.*)['\"]$", part)

                        # If there is a match, extract the package
                        if m is not None:
                            # Extract the source URL
                            # TODO: Use regexp to prevent quotes or git@github.com parts in the url, or the protocol
                            git_url = m.groupdict()["git_url"]
                            parsed_url = urlparse(git_url)
                            base = parsed_url.scheme + "://" + parsed_url.netloc
                            path = parsed_url.path
                            gem_url = urljoin(base=base, url=path)
                        # package=part.split(":")[1].strip().replace("git://","https://").replace("'","").replace('"',"")

                    # Build gem URL
                    # if (urlparse(DEFAULT_SOURCE).netloc!=urlparse(source).netloc):
                    if git_url is not None and len(git_url) > 0:
                        # The url is pointed in the gem line to a git repository
                        gem_url = git_url
                    else:
                        # TODO: Check the /gems/ part is required when a gem specify an alternate source
                        gem_url = f"{source}/api/v1/gems/{gem_name}.json"

                    if len(gem_name) > 0:
                        dependencies.append(
                            DependencyInfo(
                                name=gem_name,
                                semver_string=semver_string,
                                url=gem_url
                            )
                        )

        return dependencies

    def is_url(self, package) -> bool:
        """Check if the package argument is a well-formed URL"""
        parsed = urlparse(package)
        return (
            re.match(r"^[a-zA-Z0-9-]+(\.[a-zA-Z]{2,})+$", parsed.netloc) is not None
        ) and (parsed.path is not None)
