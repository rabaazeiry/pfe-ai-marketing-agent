// infra/mongo/init.js
// Runs the first time the mongo container spins up. Creates the app DB
// and a few indexes that Mongoose would otherwise create on boot.

const appDb = db.getSiblingDB('pfe_marketing');

appDb.createCollection('users');
appDb.users.createIndex({ email: 1 }, { unique: true });
appDb.users.createIndex({ role: 1 });
appDb.users.createIndex({ isActive: 1 });

appDb.createCollection('projects');
appDb.projects.createIndex({ userId: 1 });

appDb.createCollection('competitors');
appDb.competitors.createIndex({ projectId: 1 });

print('[init] pfe_marketing DB initialized');
