// Typed client for the FastAPI backend. Resolves the API host dynamically from the
// current page's hostname (rather than hardcoding localhost) so this also works when the
// dev server is reached over a LAN IP from another device.
export function getApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

const TOKEN_KEY = "acg_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // localStorage unavailable (private mode etc.) — auth just won't persist across reloads.
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${getApiBaseUrl()}${path}`, { ...options, headers });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // ignore body parse errors, use default message
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function get<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}
function post<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
}
function put<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined });
}
function del<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE" });
}

// ---------- Types (mirroring the backend Pydantic schemas) ----------

export interface Token {
  access_token: string;
  token_type: string;
}

export interface StudentProfile {
  id: number;
  user_id: number;
  name: string;
  class_level: number;
  school_board: string | null;
  state: string | null;
  domicile_state: string | null;
  category: string | null;
  preferred_language: string;
  preferred_study_locations: string[];
  knows_career_goal: boolean | null;
  onboarding_completed: boolean;
  created_at: string;
}

export interface NextOnboardingStep {
  step: string;
  missing_fields: string[];
  prompt: string;
}

export interface Exam {
  id: number;
  code: string;
  name: string;
  category: string;
  description: string | null;
}

export interface ExamProfile {
  id: number;
  student_profile_id: number;
  exam_code: string;
  status: string;
  attempt_year: number | null;
  score: number | null;
  percentile: number | null;
  rank: number | null;
  category_rank: number | null;
  extra: Record<string, unknown>;
  preferred_branches: string[];
  preferred_states: string[];
  preferred_cities: string[];
  college_type_preference: string | null;
  budget_max: number | null;
}

export interface MockTest {
  id: number;
  student_profile_id: number;
  exam_code: string;
  test_name: string;
  test_date: string;
  total_score: number;
  max_score: number;
  percentile: number | null;
  estimated_rank: number | null;
  subject_scores: Record<string, number>;
}

export interface SubjectTrend {
  subject: string;
  trend: string;
  average: number;
  latest: number;
}

export interface MockTestDashboard {
  test_count: number;
  average_score_pct: number | null;
  best_score_pct: number | null;
  lowest_score_pct: number | null;
  recent_average_pct: number | null;
  trend: { test_name: string; date: string; score_pct: number }[];
  subject_trends: SubjectTrend[];
  weak_subjects: string[];
  strong_subjects: string[];
  estimated_rank_range: string | null;
  estimate_disclaimer: string;
}

export interface CareerOption {
  id: number;
  name: string;
  category: string;
  description: string;
  required_subjects: string[];
  typical_entrance_exam_codes: string[];
  education_path: string;
  skills_required: string[];
  timeline: string;
  related_career_ids: number[];
  possible_challenges: string[];
  explore_next: string[];
}

export interface CareerFitResult {
  career_option_id: number;
  career_name: string;
  fit_score: number;
  fit_label: string;
  rationale: string;
  possible_challenges: string[];
  required_subjects: string[];
  required_entrance_exams: string[];
  education_path: string;
  skills_required: string[];
  timeline: string;
  alternatives: string[];
  explore_next: string[];
}

export interface CareerAssessmentOut {
  id: number;
  student_profile_id: number;
  assessment_type: string;
  results: CareerFitResult[];
  created_at: string;
}

export interface Provenance {
  source: string;
  source_url: string | null;
  academic_year: string | null;
  last_verified: string | null;
  verification_status: string;
}

export interface CollegeSummary {
  id: number;
  canonical_name: string;
  college_type: string;
  ownership: string;
  state: string;
  city: string;
  is_demo_data: boolean;
  average_rating: number | null;
  review_count: number;
}

export interface CollegeCourseOut {
  id: number;
  course_name: string;
  branch: { id: number; name: string; code: string } | null;
  exam_code: string;
  total_seats: number | null;
  provenance: Provenance;
}

export interface CollegeDetail extends CollegeSummary {
  aliases: string[];
  established_year: number | null;
  affiliated_university: string | null;
  accreditation: string | null;
  official_website: string | null;
  logo_url: string | null;
  courses_offered: CollegeCourseOut[];
}

export interface CutoffOut {
  id: number;
  year: number;
  round: number;
  category: string;
  quota: string;
  seat_type: string;
  opening_rank: number | null;
  closing_rank: number;
  provenance: Provenance;
}

export interface FeeOut {
  id: number;
  academic_year: string | null;
  tuition_fee: number | null;
  admission_fee: number | null;
  exam_fee: number | null;
  hostel_fee: number | null;
  mess_fee: number | null;
  security_deposit: number | null;
  other_charges: number | null;
  approximate_annual_cost: number;
  provenance: Provenance;
}

export interface HostelOut {
  id: number;
  hostel_type: string;
  capacity: number | null;
  room_types: string[];
  fee_annual: number | null;
  facilities: string[];
  rules: string | null;
  distance_from_academic_block_km: number | null;
  provenance: Provenance;
}

export interface PlacementOut {
  id: number;
  academic_year: string | null;
  placement_percentage: number | null;
  average_package: number | null;
  median_package: number | null;
  highest_package: number | null;
  major_recruiters: string[];
  extra: Record<string, string | number>;
  provenance: Provenance;
}

export interface NearbyPlaceOut {
  id: number;
  place_type: string;
  name: string;
  distance_km: number | null;
  approx_monthly_rent: number | null;
  source: string;
  last_updated: string | null;
}

export interface CollegeReview {
  id: number;
  college_id: number;
  rating: number;
  text: string;
  tags: string[];
  created_at: string;
}

export interface CollegeCompareRow {
  college: CollegeSummary;
  lowest_closing_rank_seen: number | null;
  approximate_annual_cost: number | null;
  hostel_available: boolean;
  placement_percentage: number | null;
  average_package: number | null;
  average_rating: number | null;
}

export interface PredictionExplanation {
  years_considered: number[];
  historical_closing_ranks: Record<string, number>;
  rounds_considered: number;
  data_freshness: string | null;
  reasoning: string;
}

export interface PredictionResultItem {
  college_id: number;
  college_name: string;
  college_type: string;
  city: string;
  state: string;
  course_name: string;
  branch_name: string | null;
  category: string;
  quota: string;
  band: "high_probability" | "possible" | "ambitious";
  band_label: string;
  band_emoji: string;
  confidence: string;
  explanation: PredictionExplanation;
  is_demo_data: boolean;
}

export interface PredictionResponse {
  exam_code: string;
  student_rank: number;
  results: PredictionResultItem[];
  disclaimer: string;
}

export interface PreferenceListItem {
  position: number;
  college_id: number;
  college_name: string;
  course_name: string;
  branch_name: string | null;
  label: string;
  explanation: string;
}

export interface PreferenceListResponse {
  items: PreferenceListItem[];
  disclaimer: string;
}

export interface RoadmapStep {
  order: number;
  title: string;
  description: string;
  status: "done" | "current" | "upcoming";
}

export interface RoadmapResponse {
  steps: RoadmapStep[];
  current_milestone: string;
  next_action: string;
  long_term_goal: string;
}

export interface SavedItem {
  id: number;
  student_profile_id: number;
  item_type: string;
  item_id: number;
  bucket: string | null;
  notes: string | null;
  created_at: string;
}

export interface ChatResponse {
  conversation_id: number;
  reply: string;
  tool_calls_used: string[];
  ai_configured: boolean;
}

export interface VoiceChatResponse extends ChatResponse {
  transcript: string;
  audio_base64: string | null;
  audio_content_type: string | null;
}

// ---------- API surface ----------

export const api = {
  auth: {
    register: (data: { email: string; password: string; name: string; class_level: number }) =>
      post<Token>("/api/auth/register", data),
    login: (data: { email: string; password: string }) => post<Token>("/api/auth/login", data),
  },
  student: {
    getProfile: () => get<StudentProfile>("/api/student/profile"),
    updateProfile: (data: Partial<StudentProfile>) => put<StudentProfile>("/api/student/profile", data),
    addAcademicRecord: (data: { academic_year: string; class_level: number; board_percentage?: number; subject_marks: Record<string, number> }) =>
      post("/api/student/academic-record", data),
    nextOnboardingStep: () => get<NextOnboardingStep>("/api/student/onboarding/next-step"),
  },
  exams: {
    list: () => get<Exam[]>("/api/exams"),
    saveProfile: (data: Partial<ExamProfile> & { exam_code: string }) => post<ExamProfile>("/api/exams/profile", data),
    getProfile: (examCode: string) => get<ExamProfile>(`/api/exams/${examCode}/profile`),
  },
  mockTests: {
    create: (data: { exam_code: string; test_name: string; test_date: string; total_score: number; max_score: number; percentile?: number; estimated_rank?: number; subject_scores: Record<string, number> }) =>
      post<MockTest>("/api/mock-tests", data),
    history: (examCode?: string) => get<MockTest[]>(`/api/mock-tests/history${examCode ? `?exam_code=${examCode}` : ""}`),
    dashboard: (examCode?: string) => get<MockTestDashboard>(`/api/mock-tests/dashboard${examCode ? `?exam_code=${examCode}` : ""}`),
  },
  careers: {
    list: () => get<CareerOption[]>("/api/careers"),
    get: (id: number) => get<CareerOption>(`/api/careers/${id}`),
    submitAssessment: (data: { assessment_type: string; responses: Record<string, unknown> }) =>
      post<CareerAssessmentOut>("/api/careers/assessment", data),
  },
  colleges: {
    search: (params: Record<string, string>) => {
      const qs = new URLSearchParams(params).toString();
      return get<CollegeSummary[]>(`/api/colleges${qs ? `?${qs}` : ""}`);
    },
    get: (id: number) => get<CollegeDetail>(`/api/colleges/${id}`),
    cutoffs: (id: number) => get<CutoffOut[]>(`/api/colleges/${id}/cutoffs`),
    fees: (id: number) => get<FeeOut[]>(`/api/colleges/${id}/fees`),
    hostel: (id: number) => get<HostelOut[]>(`/api/colleges/${id}/hostel`),
    placements: (id: number) => get<PlacementOut[]>(`/api/colleges/${id}/placements`),
    nearby: (id: number) => get<NearbyPlaceOut[]>(`/api/colleges/${id}/nearby`),
    reviews: (id: number) => get<CollegeReview[]>(`/api/colleges/${id}/reviews`),
    addReview: (id: number, data: { rating: number; text: string; tags: string[] }) =>
      post<CollegeReview>(`/api/colleges/${id}/reviews`, data),
    compare: (collegeIds: number[]) =>
      post<{ rows: CollegeCompareRow[]; ai_summary: string | null }>("/api/colleges/compare", { college_ids: collegeIds }),
  },
  predictions: {
    predictJee: (data: Record<string, unknown>) => post<PredictionResponse>("/api/predict/jee", data),
    predictNeet: (data: Record<string, unknown>) => post<PredictionResponse>("/api/predict/neet", data),
    preferenceList: (data: Record<string, unknown>) => post<PreferenceListResponse>("/api/counselling/preference-list", data),
  },
  roadmap: {
    get: () => get<RoadmapResponse>("/api/roadmap"),
  },
  savedItems: {
    list: () => get<SavedItem[]>("/api/saved-items"),
    create: (data: { item_type: string; item_id: number; bucket?: string; notes?: string }) =>
      post<SavedItem>("/api/saved-items", data),
    remove: (id: number) => del<void>(`/api/saved-items/${id}`),
  },
  ai: {
    chat: (message: string, conversationId?: number) =>
      post<ChatResponse>("/api/ai/chat", { message, conversation_id: conversationId }),
    voiceChat: (audioBlob: Blob, conversationId?: number) => {
      const form = new FormData();
      form.append("audio", audioBlob, "recording.webm");
      const qs = conversationId ? `?conversation_id=${conversationId}` : "";
      return apiFetch<VoiceChatResponse>(`/api/ai/voice-chat${qs}`, { method: "POST", body: form });
    },
  },
};
