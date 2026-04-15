import type {
  PipelineBackendStatus,
  PipelineStep,
  PipelineStepKey,
  ProjectDetail
} from './types';

export const PIPELINE_STEP_ORDER: PipelineStepKey[] = [
  'scraping',
  'cleaning',
  'classification',
  'analysis',
  'insights'
];

/**
 * Maps a backend `pipelineStatus` + `progressPercentage` to the five
 * user-facing steps. Strategy:
 *   - if pipeline is idle → every step is pending
 *   - otherwise derive `completedCount` from progressPercentage (0..100, 20% per step)
 *   - if current backend phase is a `*_in_progress` style status, mark the
 *     next uncompleted step as "running"; the trailing ones stay "pending".
 */
export function derivePipeline(project: Pick<ProjectDetail, 'pipelineStatus' | 'progressPercentage' | 'status'>): PipelineStep[] {
  const backendStatus = (project.pipelineStatus ?? 'idle') as PipelineBackendStatus;
  const pct = clamp(project.progressPercentage ?? 0, 0, 100);
  const completedCount = Math.min(PIPELINE_STEP_ORDER.length, Math.floor(pct / 20));
  const isRunning = backendStatus !== 'idle' && !backendStatus.endsWith('_complete');
  const isFailed = project.status === 'archived' ? false : false; // reserved for future

  return PIPELINE_STEP_ORDER.map((key, idx): PipelineStep => {
    if (idx < completedCount) return { key, state: 'done' };
    if (idx === completedCount) {
      if (isFailed) return { key, state: 'failed' };
      if (isRunning) return { key, state: 'running' };
    }
    return { key, state: 'pending' };
  });
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}
