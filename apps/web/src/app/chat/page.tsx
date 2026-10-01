"use client";

import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Button, Card, ErrorMessage, Input, PageHeading } from "@/components/ui";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  audioUrl?: string;
}

function ChatContent() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "Hi! I'm your AI career counsellor. Ask me about careers, JEE/NEET, or any college — I'll only use real data from our database, and I'll say so if something isn't available yet." },
  ]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<number | undefined>();
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function sendText() {
    if (!input.trim()) return;
    const text = input;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    setError(null);
    try {
      const res = await api.ai.chat(text, conversationId);
      setConversationId(res.conversation_id);
      setNotConfigured(!res.ai_configured);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the AI assistant.");
    } finally {
      setSending(false);
    }
  }

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setSending(true);
        try {
          const res = await api.ai.voiceChat(blob, conversationId);
          setConversationId(res.conversation_id);
          setNotConfigured(!res.ai_configured);
          setMessages((prev) => [
            ...prev,
            { role: "user", content: res.transcript },
            {
              role: "assistant",
              content: res.reply,
              audioUrl: res.audio_base64 ? `data:${res.audio_content_type};base64,${res.audio_base64}` : undefined,
            },
          ]);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "Could not process your voice message.");
        } finally {
          setSending(false);
        }
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecording(true);
    } catch {
      setError("Microphone access was denied or is unavailable.");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-140px)]">
      <PageHeading title="AI Career Assistant" />
      {notConfigured && (
        <ErrorMessage message="The AI assistant isn't configured yet on the server (missing API key) — everything else in the app still works." />
      )}
      <ErrorMessage message={error} />

      <Card className="flex-1 overflow-y-auto flex flex-col gap-3">
        {messages.map((m, i) => (
          <div key={i} className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.role === "user" ? "self-end bg-primary text-primary-foreground" : "self-start bg-card-border/40"}`}>
            <p className="whitespace-pre-wrap">{m.content}</p>
            {m.audioUrl && <audio controls src={m.audioUrl} className="mt-2 w-full" />}
          </div>
        ))}
        {sending && <p className="text-muted text-sm">Thinking…</p>}
      </Card>

      <form
        onSubmit={(e) => { e.preventDefault(); sendText(); }}
        className="flex gap-2"
      >
        <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about a career, exam, or college…" disabled={sending} />
        <Button type="button" variant={recording ? "secondary" : "ghost"} onClick={recording ? stopRecording : startRecording} disabled={sending}>
          {recording ? "⏹ Stop" : "🎙️"}
        </Button>
        <Button type="submit" disabled={sending || !input.trim()}>Send</Button>
      </form>
    </div>
  );
}

export default function ChatPage() {
  return (
    <ProtectedRoute>
      <ChatContent />
    </ProtectedRoute>
  );
}
