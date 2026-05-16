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
