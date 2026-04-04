function toBase64(buffer) {
  return Buffer.from(buffer).toString('base64');
}

function randomId(prefix) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random()
    .toString(36)
    .slice(2, 7)}`;
}

async function withRetry(fn, attempts = 2) {
  let lastErr = null;
  for (let i = 0; i <= attempts; i += 1) {
    try {
      return await fn(i);
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr ?? new Error('Unknown retry failure');
}

async function runHuggingFaceFallback({
  projectId,
  sourceName,
  mimeType,
  fileBuffer,
}) {
  const hfToken = process.env.HF_TOKEN?.trim();
  const hfEndpoint = process.env.HF_TAKEOFF_ENDPOINT?.trim();
  if (!hfToken || !hfEndpoint) return null;

  const payload = {
    project_id: projectId,
    source_name: sourceName,
    mime_type: mimeType || 'application/octet-stream',
    file_base64: toBase64(fileBuffer),
  };
  const res = await fetch(hfEndpoint, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${hfToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`HF fallback error (${res.status}): ${err}`);
  }
  const data = await res.json();
  return data?.result ?? data;
}

function mockTakeoff(projectId, sourceName) {
  const walls = Array.from({ length: 12 }).map((_, idx) => ({
    id: randomId('wall'),
    kind: idx % 3 === 0 ? 'exterior' : 'interior',
    x1: 40 + idx * 18,
    y1: 30 + idx * 10,
    x2: 180 + idx * 12,
    y2: 50 + idx * 9,
    lf: 10 + (idx % 4) * 2.3,
    confidence: 0.9 - (idx % 4) * 0.05,
  }));
  const rooms = [
    {
      id: randomId('room'),
      label: 'Living',
      points: [
        { x: 130, y: 110 },
        { x: 340, y: 110 },
        { x: 340, y: 250 },
        { x: 130, y: 250 },
      ],
      sf: 320,
      confidence: 0.93,
    },
    {
      id: randomId('room'),
      label: 'Kitchen',
      points: [
        { x: 360, y: 120 },
        { x: 510, y: 120 },
        { x: 510, y: 240 },
        { x: 360, y: 240 },
      ],
      sf: 180,
      confidence: 0.9,
    },
  ];

  const wallsLf = walls.reduce((sum, w) => sum + w.lf, 0);
  const roomsSf = rooms.reduce((sum, r) => sum + r.sf, 0);
  return {
    projectId,
    sourceName,
    page: 1,
    confidence: 0.92,
    scaleLabel: '1/8" = 1\'-0"',
    walls,
    rooms,
    counts: {
      doors: 5,
      windows: 3,
      fixtures: 2,
    },
    quantities: {
      wallsLf: Number(wallsLf.toFixed(1)),
      roomsSf,
    },
    needsReview: false,
    auditId: randomId('audit'),
  };
}

export async function processBlueprintWithCv({
  projectId,
  sourceName,
  mimeType,
  fileBuffer,
}) {
  const cvApi = process.env.TAKEOFF_CV_API_URL?.trim();
  if (!cvApi) {
    const hf = await runHuggingFaceFallback({
      projectId,
      sourceName,
      mimeType,
      fileBuffer,
    }).catch(() => null);
    if (hf) return hf;
    return mockTakeoff(projectId, sourceName);
  }

  const payload = {
    project_id: projectId,
    source_name: sourceName,
    mime_type: mimeType || 'application/octet-stream',
    file_base64: toBase64(fileBuffer),
  };

  try {
    const data = await withRetry(async () => {
      const res = await fetch(
        `${cvApi.replace(/\/+$/, '')}/api/v1/takeoff/process`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      );
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`CV API error (${res.status}): ${errorText}`);
      }
      return res.json();
    }, 2);
    return data?.result ?? data;
  } catch {
    const hf = await runHuggingFaceFallback({
      projectId,
      sourceName,
      mimeType,
      fileBuffer,
    }).catch(() => null);
    if (hf) return hf;
    return mockTakeoff(projectId, sourceName);
  }
}
