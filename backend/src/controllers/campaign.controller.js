// backend/src/controllers/campaign.controller.js
//
// Sert les campagnes Step 5. Source : campaign_<industry>.json produit par
// le générateur hybride :
//   scripts/campaign_generator.py → data/step5/campaigns/campaign_<industry>.json
//
// Entrée du générateur : les facts Step 4 (facts_<industry>.json). Le calendrier
// 4 semaines est ancré sur Prophet ; le LLM (llama3.1) se contente d'habiller
// le texte des posts à partir de gabarits déterministes.

const fs     = require('fs/promises');
const path   = require('path');
const { spawn } = require('child_process');

const ML_DIR = path.resolve(__dirname, '..', '..', '..', 'ml-service');

const CAMPAIGN_DIR = path.join(ML_DIR, 'data', 'step5', 'campaigns');

const CAMPAIGN_SCRIPT = path.join(ML_DIR, 'scripts', 'campaign_generator.py');

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

// ─── GET /api/campaign/:industry ─────────────────────────────────────────────
exports.getCampaignByIndustry = async (req, res, next) => {
  try {
    const industry = String(req.params.industry || '').toLowerCase().trim();

    if (!VALID_INDUSTRIES.includes(industry)) {
      return res.status(400).json({
        success: false,
        message: `Industrie invalide. Valeurs autorisées : ${VALID_INDUSTRIES.join(', ')}`
      });
    }

    const file = path.join(CAMPAIGN_DIR, `campaign_${industry}.json`);

    let raw;
    try {
      raw = await fs.readFile(file, 'utf-8');
    } catch (err) {
      if (err.code === 'ENOENT') {
        return res.status(404).json({
          success: false,
          message: `Aucun fichier de campagne pour l'industrie "${industry}"`
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

// ─── POST /api/campaign/:industry/regenerate ─────────────────────────────────
// Runs the hybrid campaign generator:
//   campaign_generator.py --industry <ind>  (template + llama3.1 — ~15 min)
// Blocks until it completes, then returns the regenerated campaign JSON.
exports.regenerateCampaign = async (req, res, next) => {
  try {
    const industry = String(req.params.industry || '').toLowerCase().trim();

    if (!VALID_INDUSTRIES.includes(industry)) {
      return res.status(400).json({
        success: false,
        message: `Industrie invalide. Valeurs autorisées : ${VALID_INDUSTRIES.join(', ')}`
      });
    }

    console.log(`🔄 Step 5 regen for "${industry}" — campaign_generator`);

    // Disable socket timeout for this long-running request (LLM ~15 min)
    req.socket.setTimeout(0);

    await _runPython(
      CAMPAIGN_SCRIPT,
      ['--industry', industry],
      `campaign_generator(${industry})`
    );

    const file = path.join(CAMPAIGN_DIR, `campaign_${industry}.json`);
    const raw = await fs.readFile(file, 'utf-8');
    const data = JSON.parse(raw);

    console.log(`📤 Campagne "${industry}" régénérée — retour au frontend`);
    return res.status(200).json({ success: true, data });
  } catch (err) {
    next(err);
  }
};
