export type ProjectStatus = 'draft' | 'active' | 'completed' | 'archived';

export type PipelineBackendStatus =
  | 'idle'
  | 'step1_extraction' | 'step1_complete'
  | 'step2_discovery'  | 'step2_complete'
  | 'step3_scraping'   | 'step3_complete'
  | 'step4_insights'   | 'step4_complete'
  | 'step5_campaign'   | 'step5_complete';

export type ProjectDetail = {
  _id: string;
  businessIdea: string;
  name?: string;
  description?: string;
  marketCategory?: string;
  industry?: string;
  country?: string;
  targetCountry?: string;
  keywords?: string[];
  targetAudience?: string[];
  status?: ProjectStatus;
  pipelineStatus?: PipelineBackendStatus;
  progressPercentage?: number;
  competitorsCount?: number;
  createdAt?: string;
  updatedAt?: string;
};

export type ScrapingStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export type CompetitorSocialMediaHandle = {
  url?: string;
  username?: string;
  followers?: number;
};

export type CompetitorClassification =
  | 'local_leader'
  | 'local_startup'
  | 'international_leader'
  | 'international_startup'
  | 'leader'
  | 'startup'
  | string;

export type CompetitorSummary = {
  _id: string;
  companyName: string;
  website?: string;
  description?: string;
  classification?: CompetitorClassification;
  classificationMaturity?: 'startup' | 'leader';
  classificationJustification?: string;
  isActive?: boolean;
  scrapingStatus?: ScrapingStatus;
  lastScrapedAt?: string;
  socialMedia?: {
    instagram?: CompetitorSocialMediaHandle;
    facebook?:  CompetitorSocialMediaHandle;
    linkedin?:  CompetitorSocialMediaHandle;
    tiktok?:    CompetitorSocialMediaHandle;
  };
};

export type PipelineStepKey =
  | 'scraping'
  | 'cleaning'
  | 'classification'
  | 'analysis'
  | 'insights';

export type PipelineStepState = 'done' | 'running' | 'pending' | 'failed';

export type PipelineStep = {
  key: PipelineStepKey;
  state: PipelineStepState;
};

export type ProjectInsights = {
  topOpportunity: string;
  topCompetitorSignal: string;
  engagementTrend: {
    label: string;
    direction: 'up' | 'down' | 'flat';
    delta: number;
  };
  recommendedAction: string;
  generatedAt?: string;
};

// ─── RAG insights (Step 4e) ──────────────────────────────────────────
export type IndustryKey = 'hotels' | 'restaurants' | 'beauty' | 'fashion' | 'patisserie';

export type RagInsightItem = {
  title: string;
  content: string;
  evidence: string;
};

export type RagQuestionBlock = {
  question_id: string;
  question_title: string;
  // The Step-4-rework pipeline (rephrase_facts.py → prose_v1 envelope)
  // does not emit question_text or retrieved_docs: it answers from
  // facts.json, not from RAG retrieval. Keep these optional so the UI
  // works on both the legacy V6 RAG envelope and the new prose_v1 one.
  question_text?: string;
  retrieved_docs?: string[];
  source_module?: string;            // present only in prose_v1
  insights?: RagInsightItem[];
  // V6 fields — rich structured output
  answer?: string;
  evidence?: string[];
  actionable_recommendations?: string[];
  ml_evidence?: string;
  raw_response?: string | null;
  status: string;
  latency_seconds: number;
  unverified_numbers?: number[];     // present only in prose_v1
};

export type IndustryInsightsBundle = {
  industry: IndustryKey;
  generated_at: string;
  model: string;
  temperature: number;
  questions: RagQuestionBlock[];
};

// ─── Campaign (Step 5) ───────────────────────────────────────────────
// Matches campaign_<industry>.json produced by scripts/campaign_generator.py.
// Per-post `status` is OK | REPAIRED | FALLBACK (kept as string, like
// RagQuestionBlock.status, to tolerate future values).

export type CampaignPost = {
  post_index: number;
  date: string;                  // ISO day, e.g. "2026-05-11"
  day_of_week: string;           // localized, e.g. "lundi"
  best_time: string;             // e.g. "22h"
  format: string;                // reel | carousel | photo | …
  theme: string;
  hashtags: string[];
  caption: string;
  hook: string;
  ad_angle: string;
  production_guide: string;
  visual_recommendation: string;
  status: string;                // OK | REPAIRED | FALLBACK
};

export type CampaignWeek = {
  week_index: number;
  week_start: string;            // ISO Monday, e.g. "2026-05-10"
  intensity: string;             // high | normal | low
  predicted_engagement: number;  // Prophet-anchored, 0..1
  posts_recommended: number;
  posts: CampaignPost[];
};

export type CampaignBundle = {
  version: string;
  industry: IndustryKey;
  generated_at: string;
  model: string;
  anchor_week: string;
  campaign_summary: {
    title: string;
    objective: string;
    target_audience: string;
    platforms: string[];
    status: string;
  };
  weeks: CampaignWeek[];
};
