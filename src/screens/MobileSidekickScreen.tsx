import { TakeoffSidekickPanel } from '@/components/TakeoffSidekickPanel';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function MobileSidekickScreen() {
  return (
    <div className="min-h-screen bg-ost-bg p-3 text-slate-100">
      <Card className="border-ost-border bg-ost-panel">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Paintbrush Mobile Sidekick</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs text-ost-muted">
          Upload a photo or PDF, review detections, ask follow-up questions, and
          schedule the next estimator step.
        </CardContent>
      </Card>
      <TakeoffSidekickPanel />
    </div>
  );
}
