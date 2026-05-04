require('dotenv').config({ path: '../.env' });
const mongoose = require('mongoose');
const fs = require('fs');
const path = require('path');

const URI = process.env.MONGODB_URI || 'mongodb://127.0.0.1:27017/battouta_db';
const BACKUP_DIR = path.join(__dirname, '../../backup/2026-04-28');

async function main() {
  fs.mkdirSync(BACKUP_DIR, { recursive: true });
  await mongoose.connect(URI);
  const db = mongoose.connection.db;
  const collections = await db.listCollections().toArray();
  console.log('Found ' + collections.length + ' collections');
  const summary = [];
  for (const col of collections) {
    const collectionName = col["name"];
    const docs = await db.collection(collectionName).find({}).toArray();
    const filePath = path.join(BACKUP_DIR, collectionName + '.json');
    fs.writeFileSync(filePath, JSON.stringify(docs, null, 2));
    const sizeKB = (fs.statSync(filePath).size / 1024).toFixed(2);
    summary.push({ collection: collectionName, docs: docs.length, sizeKB });
    console.log('OK ' + collectionName + ': ' + docs.length + ' docs');
  }
  await mongoose.disconnect();
  console.log('=== BACKUP COMPLETE ===');
  console.table(summary);
}

main().catch(err => {
  console.error('Backup failed:', err);
  process.exit(1);
});
