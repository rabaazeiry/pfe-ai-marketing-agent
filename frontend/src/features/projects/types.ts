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

export type CompetitorSummary = {
  _id: string;
  companyName: string;
  website?: string;
  description?: string;
  classificationMaturity?: 'startup' | 'leader';
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
  isMocked?: boolean;
};
