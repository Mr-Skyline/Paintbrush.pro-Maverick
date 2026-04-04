import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  createScheduleEvent,
  runTakeoffUpload,
  sidekickChat,
} from '@/lib/takeoffApi';
import { useProjectStore } from '@/store/projectStore';
import { useSidekickStore } from '@/store/sidekickStore';
import { fabric } from 'fabric';
import { useState } from 'react';

export function TakeoffSidekickPanel() {
  const projectId = useProjectStore((s) => s.projectId) ?? 'local-project';
  const uploadBusy = useSidekickStore((s) => s.uploadBusy);
  const chatBusy = useSidekickStore((s) => s.chatBusy);
  const result = useSidekickStore((s) => s.lastResult);
  const messages = useSidekickStore((s) => s.messages);
  const schedule = useSidekickStore((s) => s.schedule);
  const setUploadBusy = useSidekickStore((s) => s.setUploadBusy);
  const setChatBusy = useSidekickStore((s) => s.setChatBusy);
  const setResult = useSidekickStore((s) => s.setResult);
  const pushMessage = useSidekickStore((s) => s.pushMessage);
  const addScheduleEvent = useSidekickStore((s) => s.addScheduleEvent);

  const [chatText, setChatText] = useState('');
  const [taskTitle, setTaskTitle] = useState('Takeoff review');
  const [taskAt, setTaskAt] = useState('');
  const [taskNotes, setTaskNotes] = useState('');

  const drawOverlays = (out: NonNullable<typeof result>) => {
    const canvas = (window as unknown as { __takeoffCanvas?: fabric.Canvas })
      .__takeoffCanvas;
    if (!canvas) return;
    for (const wall of out.walls) {
      const line = new fabric.Line([wall.x1, wall.y1, wall.x2, wall.y2], {
        stroke: wall.kind === 'exterior' ? '#ef4444' : '#3b82f6',
        strokeWidth: 2,
        selectable: false,
        evented: false,
        data: { source: 'cv-overlay', confidence: wall.confidence },
      } as fabric.ILineOptions);
      canvas.add(line);
    }
    for (const room of out.rooms) {
      const poly = new fabric.Polygon(room.points, {
        fill: 'rgba(34,197,94,0.12)',
        stroke: '#22c55e',
        strokeWidth: 2,
        selectable: false,
        evented: false,
        data: { source: 'cv-overlay', confidence: room.confidence },
      });
      canvas.add(poly);
    }
    canvas.requestRenderAll();
  };

  const onUpload = async (file?: File) => {
    if (!file) return;
    setUploadBusy(true);
    try {
      const out = await runTakeoffUpload(file, projectId);
      setResult(out);
      drawOverlays(out);
      pushMessage({
        role: 'assistant',
        text: `Processed ${out.sourceName}. Walls ${out.walls.length}, rooms ${out.rooms.length}, confidence ${(out.confidence * 100).toFixed(1)}%.`,
      });
    } catch (err) {
      pushMessage({
        role: 'assistant',
        text: `Upload failed: ${String(err)}`,
      });
    } finally {
      setUploadBusy(false);
    }
  };

  const sendChat = async () => {
    const text = chatText.trim();
    if (!text) return;
    setChatText('');
    pushMessage({ role: 'user', text });
    setChatBusy(true);
    try {
      const out = await sidekickChat(projectId, text);
      pushMessage({ role: 'assistant', text: out.reply });
    } catch (err) {
      pushMessage({ role: 'assistant', text: `Chat error: ${String(err)}` });
    } finally {
      setChatBusy(false);
    }
  };

  const onSchedule = async () => {
    if (!taskTitle.trim() || !taskAt.trim()) return;
    const iso = new Date(taskAt).toISOString();
    await createScheduleEvent({
      projectId,
      title: taskTitle.trim(),
      startsAtIso: iso,
      notes: taskNotes.trim() || undefined,
    });
    addScheduleEvent({
      title: taskTitle.trim(),
      startsAtIso: iso,
      notes: taskNotes.trim() || undefined,
    });
    pushMessage({
      role: 'assistant',
      text: `Scheduled "${taskTitle.trim()}" for ${new Date(iso).toLocaleString()}.`,
    });
    setTaskNotes('');
  };

  const accuracyPct = Math.round((result?.confidence ?? 0) * 100);

  return (
    <Card className="mt-2 border-ost-border bg-ost-panel">
      <CardHeader className="py-2">
        <CardTitle className="text-sm">Takeoff Agent Sidekick</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 pb-2">
        <div className="flex items-center gap-2">
          <Input
            type="file"
            accept=".pdf,image/*"
            onChange={(e) => void onUpload(e.target.files?.[0])}
            className="text-xs"
          />
          <Button
            type="button"
            size="sm"
            disabled={uploadBusy}
            onClick={() => {
              const input = document.querySelector<HTMLInputElement>(
                'input[type="file"]'
              );
              input?.click();
            }}
          >
            {uploadBusy ? 'Running...' : 'Run'}
          </Button>
        </div>
        <div className="rounded border border-ost-border p-2">
          <div className="mb-1 flex items-center justify-between text-xs">
            <span>Detection confidence</span>
            <Badge variant={accuracyPct >= 90 ? 'default' : 'secondary'}>
              {accuracyPct}%
            </Badge>
          </div>
          <Progress value={accuracyPct} />
          {result && (
            <div className="mt-1 text-[11px] text-ost-muted">
              {result.walls.length} walls | {result.rooms.length} rooms | doors{' '}
              {result.counts.doors}
            </div>
          )}
        </div>

        <Tabs defaultValue="chat">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="chat">Chat</TabsTrigger>
            <TabsTrigger value="schedule">Schedule</TabsTrigger>
          </TabsList>
          <TabsContent value="chat" className="space-y-2">
            <ScrollArea className="h-28 rounded border border-ost-border p-2">
              {messages.length === 0 ? (
                <div className="text-xs text-ost-muted">No messages yet.</div>
              ) : (
                messages.map((m) => (
                  <div key={m.id} className="mb-2 text-xs">
                    <span className="mr-1 font-semibold capitalize">{m.role}:</span>
                    {m.text}
                  </div>
                ))
              )}
            </ScrollArea>
            <div className="flex gap-2">
              <Input
                value={chatText}
                onChange={(e) => setChatText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void sendChat();
                  }
                }}
                placeholder="Ask: why low confidence on room 2?"
              />
              <Button type="button" size="sm" disabled={chatBusy} onClick={() => void sendChat()}>
                Send
              </Button>
            </div>
          </TabsContent>
          <TabsContent value="schedule" className="space-y-2">
            <Input
              value={taskTitle}
              onChange={(e) => setTaskTitle(e.target.value)}
              placeholder="Task title"
            />
            <Input
              type="datetime-local"
              value={taskAt}
              onChange={(e) => setTaskAt(e.target.value)}
            />
            <Textarea
              value={taskNotes}
              onChange={(e) => setTaskNotes(e.target.value)}
              placeholder="Notes"
              className="min-h-[70px]"
            />
            <Button type="button" size="sm" onClick={() => void onSchedule()}>
              Update schedule
            </Button>
            <ScrollArea className="h-20 rounded border border-ost-border p-2">
              {schedule.map((evt) => (
                <div key={evt.id} className="text-xs">
                  {evt.title} - {new Date(evt.startsAtIso).toLocaleString()}
                </div>
              ))}
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
