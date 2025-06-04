class Colors:
    # ANSI escape codes for colors
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"

    @staticmethod
    def red(text):
        return f"{Colors.RED}{text}{Colors.RESET}"

    @staticmethod
    def green(text):
        return f"{Colors.GREEN}{text}{Colors.RESET}"

    @staticmethod
    def yellow(text):
        return f"{Colors.YELLOW}{text}{Colors.RESET}"

    @staticmethod
    def blue(text):
        return f"{Colors.BLUE}{text}{Colors.RESET}"

    @staticmethod
    def purple(text):
        return f"{Colors.PURPLE}{text}{Colors.RESET}"

    @staticmethod
    def cyan(text):
        return f"{Colors.CYAN}{text}{Colors.RESET}"

    @staticmethod
    def gray(text):
        return f"{Colors.GRAY}{text}{Colors.RESET}"
