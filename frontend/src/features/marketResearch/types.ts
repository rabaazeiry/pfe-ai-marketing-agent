export type MarketResearchStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export type DominantPlatform = 'instagram' | 'facebook' | 'linkedin' | 'tiktok' | '';

export type MarketMaturity = 'emerging' | 'growing' | 'mature' | 'declining' | 'unknown';

export type MarketOverview = {
  totalCompetitors: number;
  leaderCount: number;
  startupCount: number;
  localCount: number;
  internationalCount: number;
  dominantPlatform: DominantPlatform;
  marketMaturity: MarketMaturity;
};

export type ClassificationBucket = {
  classification: 'startup' | 'leader' | 'local' | 'international';
  count: number;
  competitors: string[];
};

export type MarketResearch = {
  _id: string;
  projectId: string;
  status: MarketResearchStatus;
  aiModelUsed?: string;
  generatedAt?: string | null;
  error?: string;
  marketSummary: {
    content: string;
    generatedAt?: string | null;
    competitorsAnalyzed?: number;
  };
  marketOverview: MarketOverview;
  classificationSummary?: ClassificationBucket[];
  createdAt?: string;
  updatedAt?: string;
};
