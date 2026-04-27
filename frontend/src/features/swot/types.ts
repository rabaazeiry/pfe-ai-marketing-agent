export type SwotStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export type SwotSource = {
  type: 'llm' | 'fallback';
  reason?: string;
};

export type SwotFacts = {
  followers: number;
  engagementRate: number;
  postsPerWeek: number;
  contentMix: Record<string, number>;
  topHashtags: string[];
  platforms: string[];
  classificationMaturity: string;
  geographicScope: string;
  industry: string;
  country: string;
  sectorAvgEngagement: number | null;
  sectorAvgPostsPerWeek: number | null;
  sectorLeaderCount: number | null;
  sectorStartupCount: number | null;
  sectorDominantPlatform: string;
  sectorMaturity: string;
  hasMarketSummary: boolean;
};

export type SwotQuadrantKey = 'strengths' | 'weaknesses' | 'opportunities' | 'threats';

export type SwotAnalysis = {
  _id: string;
  competitorId: string;
  projectId: string;
  companyName: string;
  status: SwotStatus;
  aiModelUsed?: string;
  generatedAt?: string | null;
  error?: string;
  facts: SwotFacts;
  swot: Record<SwotQuadrantKey, string>;
  sources: Record<SwotQuadrantKey, SwotSource>;
  createdAt?: string;
  updatedAt?: string;
};
