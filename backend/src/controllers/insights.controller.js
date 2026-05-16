// backend/src/controllers/insights.controller.js
//
// Sert les insights Step 4. Source : insights_<industry>.json produit par
// le pipeline déterministe en deux temps :
//   1. compute_facts.py  → data/step4f_v6/facts/facts_<industry>.json
//   2. rephrase_facts.py → data/step4f_v6/insights/insights_<industry>.json
//
// Le RAG/Chroma (step4f_v6_03_generate_insights.py) n'est plus dans le
// chemin critique de Step 4 — il calculait des nombres avec un LLM et
// les recyclait entre modules. La logique de calcul est désormais
// Python pur ; le LLM se contente de reformuler le JSON.

const fs     = require('fs/promises');
const path   = require('path');
const { spawn } = require('child_process');

const ML_DIR = path.resolve(__dirname, '..', '..', '..', 'ml-service');

const INSIGHTS_DIR = path.join(ML_DIR, 'data', 'step4f_v6', 'insights');

const COMPUTE_FACTS_SCRIPT  = path.join(ML_DIR, 'scripts', 'compute_facts.py');
const REPHRASE_FACTS_SCRIPT = path.join(ML_DIR, 'scripts', 'rephrase_facts.py');

// Python executable inside ml-service venv (Windows path)
const PYTHON_EXE = path.join(ML_DIR, '.venv', 'Scripts', 'python.exe');

const VALID_INDUSTRIES = ['hotels', 'restaurants', 'beauty', 'fashion', 'patisserie'];

function _runPython(scriptPath, args, label) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      PYTHON_EXE,
      ['-X', 'utf8', scriptPath, ...args],
      {
        env: {
          ...process.env,
          PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION: 'python',
        },
      }
    );
    child.stdout.on('data', (d) => process.stdout.write(d));
    child.stderr.on('data', (d) => process.stderr.write(d));
    child.on('error', (err) => {
      console.error(`❌ Spawn error (${label}):`, err.message);
      reject(err);
    });
    child.on('close', (code) => {
      if (code === 0) {
        console.log(`✅ ${label} terminé`);
        resolve();
      } else {
        reject(new Error(`${label} a retourné le code ${code}`));
      }
    });
  });
}

// ─── GET /api/insights/:industry ────────────────────────────────────────────
exports.getInsightsByIndustry = async (req, res, next) => {
  try {
    const industry = String(req.params.industry || '').toLowerCase().trim();

    if (!VALID_INDUSTRIES.includes(industry)) {
      return res.status(400).json({
        success: false,
        message: `Industrie invalide. Valeurs autorisées : ${VALID_INDUSTRIES.join(', ')}`
      });
    }

    const file = path.join(INSIGHTS_DIR, `insights_${industry}.json`);

    let raw;
    try {
      raw = await fs.readFile(file, 'utf-8');
    } catch (err) {
      if (err.code === 'ENOENT') {
        return res.status(404).json({
          success: false,
          message: `Aucun fichier d'insights pour l'industrie "${industry}"`
        });
      }
      throw err;
    }

    const data = JSON.parse(raw);
    return res.status(200).json({ success: true, data });
  } catch (err) {
    next(err);
  }
};

// ─── POST /api/insights/:industry/regenerate ─────────────────────────────────
// Runs the two-stage deterministic pipeline:
//   1. compute_facts.py   (Python pandas — fast, ~1s)
//   2. rephrase_facts.py  (LLM rephrasing — ~8-10 min per industry)
// Blocks until both complete, then returns the regenerated insights JSON.
exports.regenerateInsights = async (req, res, next) => {
  try {
    const industry = String(req.params.industry || '').toLowerCase().trim();

    if (!VALID_INDUSTRIES.includes(industry)) {
      return res.status(400).json({
        success: false,
        message: `Industrie invalide. Valeurs autorisées : ${VALID_INDUSTRIES.join(', ')}`
      });
    }

    console.log(`🔄 Step 4 regen for "${industry}" — compute_facts → rephrase_facts`);

    // Disable socket timeout for this long-running request (rephrase ~10 min)
    req.socket.setTimeout(0);

    await _runPython(
      COMPUTE_FACTS_SCRIPT,
      ['--industry', industry],
      `compute_facts(${industry})`
    );

    await _runPython(
      REPHRASE_FACTS_SCRIPT,
      ['--industry', industry],
      `rephrase_facts(${industry})`
    );

    const file = path.join(INSIGHTS_DIR, `insights_${industry}.json`);
    const raw = await fs.readFile(file, 'utf-8');
    const data = JSON.parse(raw);

    console.log(`📤 Insights "${industry}" régénérés — retour au frontend`);
    return res.status(200).json({ success: true, data });
  } catch (err) {
    next(err);
  }
};
