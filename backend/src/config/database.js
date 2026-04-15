// src/config/database.js

const mongoose = require('mongoose');
const { MONGODB_URI } = require('./env');

const LOCAL_URI = 'mongodb://127.0.0.1:27017/battouta_db';

/**
 * Connects to the local MongoDB instance (battouta_db on 127.0.0.1:27017).
 * Falls back to the local URI if MONGODB_URI is not set in .env.
 */
const connectDB = async () => {
  const uri = MONGODB_URI || LOCAL_URI;

  try {
    console.log('⏳ Connecting to MongoDB (local)...');

    const options = {
      serverSelectionTimeoutMS: 5000,
      socketTimeoutMS: 45000
    };

    await mongoose.connect(uri, options);

    console.log('✅ MongoDB Connected');
    console.log('📁 Database:', mongoose.connection.name);
  } catch (error) {
    console.error('❌ MongoDB Connection Error:', error.message);
    process.exit(1);
  }
};

module.exports = connectDB;
