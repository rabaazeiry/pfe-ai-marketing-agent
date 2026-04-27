// src/config/env.js

require('dotenv').config();

module.exports = {
  NODE_ENV: process.env.NODE_ENV || 'development',
  PORT: process.env.PORT || 5000,
  FRONTEND_URL: process.env.FRONTEND_URL || 'http://localhost:5173',

  MONGODB_URI: process.env.MONGODB_URI,

  JWT_SECRET: process.env.JWT_SECRET,
  JWT_EXPIRES_IN: process.env.JWT_EXPIRES_IN || '24h',

  SCRAPER_URL: process.env.SCRAPER_URL || 'http://localhost:8000',
  N8N_WEBHOOK_URL: process.env.N8N_WEBHOOK_URL || 'http://localhost:5678',
  N8N_WEBHOOK_SECRET: process.env.N8N_WEBHOOK_SECRET || '',

  OPENAI_API_KEY: process.env.OPENAI_API_KEY || '',
  GROQ_API_KEY: process.env.GROQ_API_KEY || '',
  VALUESERP_API_KEY: process.env.VALUESERP_API_KEY || '',
  SERPER_API_KEY: process.env.SERPER_API_KEY || '',
  TAVILY_API_KEY: process.env.TAVILY_API_KEY || '',
  CHROMA_API_KEY: process.env.CHROMA_API_KEY || '',
  CHROMA_TENANT: process.env.CHROMA_TENANT || '',
  CHROMA_DATABASE: process.env.CHROMA_DATABASE || '',
  APIFY_API_KEY: process.env.APIFY_API_KEY || '',

  OLLAMA_URL: process.env.OLLAMA_URL || 'http://localhost:11434/api/generate',
  OLLAMA_MODEL: process.env.OLLAMA_MODEL || 'llama3.1',
  OLLAMA_TIMEOUT_MS: Number(process.env.OLLAMA_TIMEOUT_MS || 600000)
};
