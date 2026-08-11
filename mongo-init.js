// Runs once on first Mongo volume init (docker-entrypoint-initdb.d).
// Creates the application user with scoped readWrite on the app database.
// Root admin is created by MONGO_INITDB_ROOT_USERNAME / _PASSWORD.

const dbName = process.env.MONGODB_DB || "hf_market_engine";
const appUser = process.env.MONGO_APP_USER || "app";
const appPass = process.env.MONGO_APP_PASSWORD;

if (!appPass) {
    print("ERROR: MONGO_APP_PASSWORD not set — skipping app user creation.");
    quit(1);
}

// Create the app user in the admin database (authSource=admin in the app's
// connection string) but scope its privileges to the application database only.
db.getSiblingDB("admin").createUser({
    user: appUser,
    pwd: appPass,
    roles: [{ role: "readWrite", db: dbName }],
});

print(`Created app user '${appUser}' on database '${dbName}'.`);
