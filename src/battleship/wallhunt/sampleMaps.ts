import type { WallHuntMap } from '@/battleship/wallhunt/types';

export const defaultWallHuntMaps = (): WallHuntMap[] => [
  {
    mapId: 'sample-floor-1',
    width: 1920,
    height: 1080,
    walls: [
      {
        wallId: 'w-perimeter-north',
        className: 'perimeter',
        polyline: [
          { x: 240, y: 180 },
          { x: 1620, y: 180 },
        ],
        tolerancePx: 12,
        maxSegments: 6,
        requiredCoverage: 0.84,
      },
      {
        wallId: 'w-interior-core',
        className: 'interior',
        polyline: [
          { x: 840, y: 260 },
          { x: 840, y: 820 },
          { x: 1180, y: 820 },
          { x: 1180, y: 260 },
        ],
        tolerancePx: 12,
        maxSegments: 9,
        requiredCoverage: 0.8,
      },
      {
        wallId: 'w-corridor-south',
        className: 'interior',
        polyline: [
          { x: 300, y: 860 },
          { x: 1580, y: 860 },
        ],
        tolerancePx: 12,
        maxSegments: 7,
        requiredCoverage: 0.86,
      },
    ],
  },
];

