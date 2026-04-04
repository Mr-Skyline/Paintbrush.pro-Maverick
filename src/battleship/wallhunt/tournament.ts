import { spawnNextGeneration } from '@/battleship/wallhunt/evolution';
import { runWallEpisode } from '@/battleship/wallhunt/env';
import { evaluateQualification } from '@/battleship/wallhunt/qualification';
import { appendTransition, createReplayBuffers } from '@/battleship/wallhunt/replay';
import type {
  QualificationMode,
  RoundResult,
  TournamentResult,
  WallEpisodeResult,
  WallHuntAgent,
  WallInteractionConfig,
  WallHuntMap,
  OstButtonTarget,
} from '@/battleship/wallhunt/types';

const toMdReport = (result: TournamentResult): string => {
  const lines: string[] = [];
  lines.push(`# Wall Battleship Tournament Report`);
  lines.push('');
  lines.push(`- created_at: ${result.createdAt}`);
  lines.push(`- mode: ${result.mode}`);
  lines.push(`- maps: ${result.maps.join(', ')}`);
  lines.push('');
  for (const round of result.rounds) {
    lines.push(`## Round ${round.round}`);
    lines.push(`- winners: ${round.winners.join(', ') || 'none'}`);
    lines.push(`- losers: ${round.losers.join(', ') || 'none'}`);
    lines.push(`| agent | score | completed_walls | segments | invalid_actions | qualified |`);
    lines.push(`|---|---:|---:|---:|---:|---:|`);
    for (const row of round.leaderboard) {
      lines.push(
        `| ${row.agentId} | ${row.score.toFixed(2)} | ${row.completedWalls} | ${row.segmentsTotal} | ${row.invalidActions} | ${row.qualificationPass ? 'yes' : 'no'} |`
      );
    }
    lines.push('');
  }
  return lines.join('\n');
};

const aggregateAgentResult = (episodes: WallEpisodeResult[]): {
  score: number;
  completedWalls: number;
  segments: number;
  invalidActions: number;
} => ({
  score: episodes.reduce((sum, e) => sum + e.score, 0),
  completedWalls: episodes.reduce((sum, e) => sum + e.completedWallCount, 0),
  segments: episodes.reduce((sum, e) => sum + e.segmentsTotal, 0),
  invalidActions: episodes.reduce(
    (sum, e) => sum + Math.round(e.invalidRate * Math.max(1, e.turns)),
    0
  ),
});

export const runWallTournament = (opts: {
  maps: WallHuntMap[];
  initialPopulation: WallHuntAgent[];
  rounds: number;
  winnersPerRound: number;
  mode: QualificationMode;
  mutationRate: number;
  buttonTargets: OstButtonTarget[];
  interactionConfig?: WallInteractionConfig;
}): { result: TournamentResult; reportMarkdown: string } => {
  const replay = createReplayBuffers();
  const rounds: RoundResult[] = [];
  let population = opts.initialPopulation.slice();

  for (let round = 1; round <= opts.rounds; round += 1) {
    const qualification = population.map((agent) =>
      evaluateQualification({
        agent,
        buttons: opts.buttonTargets,
        mode: opts.mode,
      })
    );
    const qualified = qualification
      .filter((q) => q.pass)
      .map((q) => population.find((a) => a.id === q.agentId))
      .filter(Boolean) as WallHuntAgent[];

    const episodeRows: WallEpisodeResult[] = [];
    for (const agent of qualified) {
      for (const map of opts.maps) {
        const ep = runWallEpisode({
          map,
          agent,
          maxTurns: 220,
          interactionConfig: opts.interactionConfig,
        });
        ep.mode = opts.mode;
        episodeRows.push(ep);
        for (const step of ep.trace) {
          appendTransition(replay, {
            mapId: ep.mapId,
            wallId: step.hitWallId,
            point: step.point,
            scoreDelta: step.scoreDelta,
            validHit: step.validHit,
          });
        }
      }
    }

    const grouped = new Map<string, WallEpisodeResult[]>();
    for (const ep of episodeRows) {
      const rows = grouped.get(ep.agentId) ?? [];
      rows.push(ep);
      grouped.set(ep.agentId, rows);
    }

    const leaderboard = population.map((agent) => {
      const runs = grouped.get(agent.id) ?? [];
      const agg = aggregateAgentResult(runs);
      const q = qualification.find((x) => x.agentId === agent.id);
      return {
        agentId: agent.id,
        score: agg.score,
        completedWalls: agg.completedWalls,
        segmentsTotal: agg.segments,
        invalidActions: agg.invalidActions,
        qualificationPass: !!q?.pass,
      };
    });

    leaderboard.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.completedWalls !== a.completedWalls) return b.completedWalls - a.completedWalls;
      return a.segmentsTotal - b.segmentsTotal;
    });

    const winners = leaderboard
      .filter((r) => r.qualificationPass)
      .slice(0, Math.max(1, opts.winnersPerRound))
      .map((r) => r.agentId);
    const losers = leaderboard
      .filter((r) => !winners.includes(r.agentId))
      .map((r) => r.agentId);

    rounds.push({
      round,
      winners,
      losers,
      leaderboard,
      qualification,
      episodes: episodeRows,
    });

    const winnerAgents = population.filter((a) => winners.includes(a.id));
    if (round < opts.rounds) {
      population = spawnNextGeneration({
        winners: winnerAgents,
        populationSize: population.length,
        mutationRate: opts.mutationRate,
      });
    } else {
      population = winnerAgents;
    }
  }

  const result: TournamentResult = {
    createdAt: new Date().toISOString(),
    mode: opts.mode,
    maps: opts.maps.map((m) => m.mapId),
    rounds,
    finalWinnerIds: rounds[rounds.length - 1]?.winners ?? [],
    winnersArtifact: {
      winners: rounds.flatMap((r) => r.winners),
      replayPositiveCount: replay.positive.length,
    },
    losersArtifact: {
      losers: rounds.flatMap((r) => r.losers),
      replayNegativeCount: replay.negative.length,
    },
  };
  return { result, reportMarkdown: toMdReport(result) };
};

