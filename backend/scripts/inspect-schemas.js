// READ-ONLY schema inspector for Phase 1 (Data Loading) planning.
// Shows 1 sample document from projects, competitors, and socialanalyses
// with all keys, nested object structures, and field types.
const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '..', '.env') });
const mongoose = require('mongoose');
require('../src/models');
const connectDB = require('../src/config/database');

const MAX_STR = 80;

function describe(value, depth = 0) {
  if (value === null) return { __type: 'null' };
  if (value === undefined) return { __type: 'undefined' };
  const t = typeof value;

  if (t === 'string') {
    const truncated = value.length > MAX_STR ? value.slice(0, MAX_STR) + '...' : value;
    return { __type: 'string', __len: value.length, __sample: truncated };
  }
  if (t === 'number') return { __type: Number.isInteger(value) ? 'int' : 'float', __sample: value };
  if (t === 'boolean') return { __type: 'boolean', __sample: value };
  if (t === 'bigint') return { __type: 'bigint', __sample: String(value) };

  if (value instanceof Date) return { __type: 'Date', __sample: value.toISOString() };
  if (value instanceof mongoose.Types.ObjectId) return { __type: 'ObjectId', __sample: String(value) };
  if (Buffer.isBuffer(value)) return { __type: 'Buffer', __len: value.length };

  if (Array.isArray(value)) {
    return {
      __type: 'array',
      __len: value.length,
      __itemSample: value.length ? describe(value[0], depth + 1) : null,
    };
  }

  if (t === 'object') {
    const out = { __type: 'object' };
    for (const k of Object.keys(value)) {
      out[k] = describe(value[k], depth + 1);
    }
    return out;
  }

  return { __type: t, __sample: String(value) };
}

(async () => {
  await connectDB();
  const db = mongoose.connection.db;

  const result = {};

  // 1) projects
  const projectDoc = await db.collection('projects').findOne({});
  result.projects = {
    __collection: 'projects',
    __totalDocs: await db.collection('projects').countDocuments(),
    __sampleId: projectDoc ? String(projectDoc._id) : null,
    __schema: projectDoc ? describe(projectDoc) : null,
  };

  // 2) competitors
  const competitorDoc = await db.collection('competitors').findOne({});
  result.competitors = {
    __collection: 'competitors',
    __totalDocs: await db.collection('competitors').countDocuments(),
    __sampleId: competitorDoc ? String(competitorDoc._id) : null,
    __schema: competitorDoc ? describe(competitorDoc) : null,
  };

  // 3) socialanalyses — 1 doc that actually has recentPosts, prefer most recent post
  const saDoc = await db.collection('socialanalyses').findOne(
    { 'recentPosts.0': { $exists: true } },
    { sort: { lastScrapedAt: -1 } }
  );

  let saSchema = null;
  let postSchema = null;
  if (saDoc) {
    // Pick the most recent post for the post-level sample
    const posts = Array.isArray(saDoc.recentPosts) ? saDoc.recentPosts.slice() : [];
    posts.sort((a, b) => {
      const ta = new Date(a?.publishedAt || a?.createdAt || 0).getTime();
      const tb = new Date(b?.publishedAt || b?.createdAt || 0).getTime();
      return tb - ta;
    });
    const mostRecentPost = posts[0] || null;

    // Full doc schema, but replace recentPosts array sample with summary only
    const docCopy = { ...saDoc };
    docCopy.recentPosts = `<<array of ${posts.length} posts — see __recentPostSample below>>`;
    saSchema = describe(docCopy);
    postSchema = mostRecentPost ? describe(mostRecentPost) : null;
  }

  result.socialanalyses = {
    __collection: 'socialanalyses',
    __totalDocs: await db.collection('socialanalyses').countDocuments(),
    __docsWithRecentPosts: await db.collection('socialanalyses').countDocuments({ 'recentPosts.0': { $exists: true } }),
    __sampleId: saDoc ? String(saDoc._id) : null,
    __schema: saSchema,
    __recentPostsLen: saDoc?.recentPosts?.length ?? 0,
    __recentPostSample: postSchema,
  };

  console.log(JSON.stringify(result, null, 2));

  await mongoose.disconnect();
})().catch((err) => {
  console.error('inspect-schemas error:', err);
  process.exit(1);
});
