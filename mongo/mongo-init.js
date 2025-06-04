// Switch to depscan database (creates it if doesn't exist)
db = db.getSiblingDB('depscanner');

// Create collections
db.createCollection('organizations');
db.createCollection('repositories');
db.createCollection('packages');
db.createCollection('scopes');

// Create indexes for better performance
db.repositories.createIndex({ "name": 1 }, { unique: true });
db.repositories.createIndex({ "owner.login": 1}, {collation: {locale: 'en', strength: 1}});
db.packages.createIndex({ "name": 1, "registry": 1}, {unique: true});
db.dependencies.createIndex({ "repo_name": 1, "package_name": 1, "semver": 1, "dependency_file": 1}, {unique: true});
db.scopes.createIndex({ "name": 1}, {unique: true});
