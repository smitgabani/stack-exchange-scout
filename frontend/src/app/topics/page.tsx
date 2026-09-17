"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { colorForTopic } from "@/lib/topic-color";
import styles from "./topics.module.css";

// What the backend actually does with this page's fields, in the order it does
// it: filter_service.evaluate rejects, then ranking_service.score_topic_relevance
// ranks, then profile_service.apply_patch re-syncs the Scout query.
const TOPIC_GUIDE = [
  {
    title: "Matching is literal",
    body: "A question is yours when a topic name appears in its tags or title. “rust” matches; “systems programming” almost never will.",
  },
  {
    title: "No match, no question",
    body: "A question matching none of your topics is dropped before it is ever scored, however good it looks otherwise.",
  },
  {
    title: "Weight ranks, it doesn’t filter",
    body: "The heaviest matching topic sets the topic score, which is 30% of a question’s Match %. Matching several topics adds a small bonus.",
  },
  {
    title: "Preferred nudges, Avoid rejects",
    body: "A preferred concept found anywhere in the question adds a bonus. An avoided concept throws the question out.",
  },
  {
    title: "Saving re-aims the Scout",
    body: "Your topics are rewritten into the search the Scout runs next. Questions already found are kept, scored under the profile version they arrived with.",
  },
];

function TopicGuide() {
  const dialog = useRef<HTMLDialogElement>(null);

  return (
    <>
      <button type="button" className={styles.guideOpen} onClick={() => dialog.current?.showModal()}>
        How topics work
      </button>
      {/* <dialog>/showModal gives Esc-to-close, a focus trap and ::backdrop for
          free — none of which a hand-rolled div overlay would have. */}
      <dialog
        ref={dialog}
        className={styles.guide}
        onClick={(event) => event.target === dialog.current && dialog.current?.close()}
      >
        <div className={styles.guideInner}>
          <div className={styles.guideHead}>
            <div className={styles.guideTitle}>How topics work</div>
            <button
              type="button"
              className={styles.guideClose}
              onClick={() => dialog.current?.close()}
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <ol className={styles.guideList}>
            {TOPIC_GUIDE.map((item) => (
              <li key={item.title} className={styles.guideItem}>
                <div className={styles.guideItemTitle}>{item.title}</div>
                <div className={styles.guideItemBody}>{item.body}</div>
              </li>
            ))}
          </ol>
        </div>
      </dialog>
    </>
  );
}

type Topic = { name: string; weight: number };
type Difficulty = { minimum: number; maximum: number };
type QuestionPreferences = {
  prefer_unanswered: boolean;
  max_answers: number;
  prefer_recent: boolean;
  exclude_closed: boolean;
  exclude_duplicates: boolean;
};
type Digest = { frequency_days: number; questions: number };
type ProfileData = {
  topics: Topic[];
  preferred_concepts: string[];
  excluded_concepts: string[];
  difficulty: Difficulty;
  question_preferences: QuestionPreferences;
  digest: Digest;
};

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => (entry && typeof entry === "object" && "msg" in entry ? String(entry.msg) : JSON.stringify(entry)))
      .join("; ");
  }
  return JSON.stringify(detail);
}

async function fetchProfile(): Promise<{ data: ProfileData; version: number }> {
  const response = await fetch("/api/profile");
  if (!response.ok) {
    throw new Error(`failed to fetch profile: ${response.status}`);
  }
  return response.json();
}

function Stepper({
  value,
  onDecrement,
  onIncrement,
}: {
  value: number;
  onDecrement: () => void;
  onIncrement: () => void;
}) {
  return (
    <div className={styles.stepper}>
      <button className={styles.stepBtn} onClick={onDecrement} type="button">
        −
      </button>
      <div className={styles.stepVal}>{value}</div>
      <button className={styles.stepBtn} onClick={onIncrement} type="button">
        +
      </button>
    </div>
  );
}

function PrefToggleRow({
  name,
  hint,
  on,
  onToggle,
}: {
  name: string;
  hint: string;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={styles.prefRow}>
      <div className={styles.prefText}>
        <div className={styles.prefName}>{name}</div>
        <div className={styles.prefHint}>{hint}</div>
      </div>
      <button
        type="button"
        className={`${styles.toggleSwitch} ${on ? styles.on : ""}`}
        onClick={onToggle}
        aria-pressed={on}
      >
        <div className={styles.toggleKnob} />
      </button>
    </div>
  );
}

function ConceptCard({
  title,
  values,
  excluded,
  onAdd,
  onRemove,
}: {
  title: string;
  values: string[];
  excluded: boolean;
  onAdd: (value: string) => void;
  onRemove: (value: string) => void;
}) {
  const [value, setValue] = useState("");

  function submit() {
    if (!value.trim()) return;
    onAdd(value.trim());
    setValue("");
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>{title}</div>
      <div className={styles.chipRow}>
        {values.map((concept) => (
          <div
            key={concept}
            className={`${styles.chip} ${excluded ? styles.excluded : ""} ${styles.on}`}
            onClick={() => onRemove(concept)}
          >
            {concept} ×
          </div>
        ))}
      </div>
      <div className={styles.addRow}>
        <input
          placeholder={`Add ${excluded ? "excluded" : "preferred"} concept`}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && submit()}
        />
        <button className={styles.addTopic} onClick={submit} type="button">
          + Add
        </button>
      </div>
    </div>
  );
}

export default function TopicsPage() {
  const queryClient = useQueryClient();
  const { data: profile, isLoading } = useQuery({ queryKey: ["profile"], queryFn: fetchProfile });

  const [form, setForm] = useState<ProfileData | null>(null);
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [newTopicName, setNewTopicName] = useState("");
  const [saving, setSaving] = useState(false);
  const [showSaved, setShowSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Adjust local form state when a new profile version arrives from the
  // server, rather than in a useEffect (react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes) —
  // avoids an extra render and won't clobber in-progress edits, since the
  // version only changes after this component's own save.
  if (profile && loadedVersion !== profile.version) {
    setForm(profile.data);
    setLoadedVersion(profile.version);
  }

  if (isLoading || !form) {
    return <main className={styles.page}>Loading…</main>;
  }

  function update(patch: Partial<ProfileData>) {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));
    setShowSaved(false);
  }

  function updateTopicWeight(index: number, weight: number) {
    const topics = form!.topics.slice();
    topics[index] = { ...topics[index], weight };
    update({ topics });
  }

  function removeTopic(index: number) {
    const topics = form!.topics.slice();
    topics.splice(index, 1);
    update({ topics });
  }

  function addTopic() {
    if (!newTopicName.trim()) return;
    update({ topics: [...form!.topics, { name: newTopicName.trim(), weight: 50 }] });
    setNewTopicName("");
  }

  function addConcept(list: "preferred_concepts" | "excluded_concepts", value: string) {
    if (form![list].some((c) => c.toLowerCase() === value.toLowerCase())) return;
    update({ [list]: [...form![list], value] } as Partial<ProfileData>);
  }

  function removeConcept(list: "preferred_concepts" | "excluded_concepts", value: string) {
    update({ [list]: form![list].filter((c) => c !== value) } as Partial<ProfileData>);
  }

  async function handleSave() {
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch("/api/profile", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(formatErrorDetail(body.detail));
        return;
      }
      setForm(body.data);
      await queryClient.invalidateQueries({ queryKey: ["profile"] });
      setShowSaved(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className={styles.page}>
      <div>
        <div className={styles.pageTitle}>My interests</div>
        <div className={styles.pageSub}>
          Changing topics never deletes questions already discovered — they just keep their old profile version.
        </div>
        <TopicGuide />
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.card}>
        <div className={styles.cardTitle}>Topics</div>
        {form.topics.map((topic, index) => (
          <div className={styles.topicRow} key={`${topic.name}-${index}`}>
            <div className={styles.topicAvatar} style={{ background: colorForTopic(topic.name) }}>
              {topic.name.charAt(0).toUpperCase()}
            </div>
            <div className={styles.topicName}>{topic.name}</div>
            <input
              className={styles.topicSlider}
              type="range"
              min={0}
              max={100}
              value={topic.weight}
              onChange={(event) => updateTopicWeight(index, Number(event.target.value))}
            />
            <div className={styles.topicPct}>{Math.round(topic.weight)}%</div>
            <button
              className={styles.removeTopic}
              onClick={() => removeTopic(index)}
              aria-label={`Remove ${topic.name}`}
              type="button"
            >
              ×
            </button>
          </div>
        ))}
        <div className={styles.addRow}>
          <input
            placeholder="New topic name"
            value={newTopicName}
            onChange={(event) => setNewTopicName(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && addTopic()}
          />
          <button className={styles.addTopic} onClick={addTopic} type="button">
            + Add topic
          </button>
        </div>
      </div>

      <ConceptCard
        title="Preferred concepts"
        values={form.preferred_concepts}
        excluded={false}
        onAdd={(value) => addConcept("preferred_concepts", value)}
        onRemove={(value) => removeConcept("preferred_concepts", value)}
      />

      <ConceptCard
        title="Avoid"
        values={form.excluded_concepts}
        excluded
        onAdd={(value) => addConcept("excluded_concepts", value)}
        onRemove={(value) => removeConcept("excluded_concepts", value)}
      />

      <div className={styles.card}>
        <div className={styles.cardTitle}>Difficulty</div>
        <div className={styles.diffRow}>
          <div className={styles.diffField}>
            <div className={styles.diffLabel}>Minimum</div>
            <Stepper
              value={form.difficulty.minimum}
              onDecrement={() =>
                update({ difficulty: { ...form.difficulty, minimum: Math.max(1, form.difficulty.minimum - 1) } })
              }
              onIncrement={() =>
                update({
                  difficulty: {
                    ...form.difficulty,
                    minimum: Math.min(form.difficulty.maximum, form.difficulty.minimum + 1),
                  },
                })
              }
            />
          </div>
          <div className={styles.diffField}>
            <div className={styles.diffLabel}>Maximum</div>
            <Stepper
              value={form.difficulty.maximum}
              onDecrement={() =>
                update({
                  difficulty: {
                    ...form.difficulty,
                    maximum: Math.max(form.difficulty.minimum, form.difficulty.maximum - 1),
                  },
                })
              }
              onIncrement={() =>
                update({ difficulty: { ...form.difficulty, maximum: Math.min(5, form.difficulty.maximum + 1) } })
              }
            />
          </div>
        </div>
        <div className={styles.pageSub}>
          Showing questions rated {form.difficulty.minimum}–{form.difficulty.maximum} out of 5.
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Question preferences</div>
        <PrefToggleRow
          name="Prefer unanswered questions"
          hint="Rank questions with fewer existing answers higher."
          on={form.question_preferences.prefer_unanswered}
          onToggle={() =>
            update({
              question_preferences: {
                ...form.question_preferences,
                prefer_unanswered: !form.question_preferences.prefer_unanswered,
              },
            })
          }
        />
        <PrefToggleRow
          name="Prefer recent questions"
          hint="Rank newer questions higher over otherwise-similar older ones."
          on={form.question_preferences.prefer_recent}
          onToggle={() =>
            update({
              question_preferences: {
                ...form.question_preferences,
                prefer_recent: !form.question_preferences.prefer_recent,
              },
            })
          }
        />
        <div className={styles.prefRow}>
          <div className={styles.prefText}>
            <div className={styles.prefName}>Maximum existing answers</div>
            <div className={styles.prefHint}>Skip questions that already have more answers than this.</div>
          </div>
          <Stepper
            value={form.question_preferences.max_answers}
            onDecrement={() =>
              update({
                question_preferences: {
                  ...form.question_preferences,
                  max_answers: Math.max(0, form.question_preferences.max_answers - 1),
                },
              })
            }
            onIncrement={() =>
              update({
                question_preferences: {
                  ...form.question_preferences,
                  max_answers: Math.min(10, form.question_preferences.max_answers + 1),
                },
              })
            }
          />
        </div>
        <hr className={styles.hr} />
        <div className={`${styles.prefRow} ${styles.locked}`}>
          <div className={styles.prefText}>
            <div className={styles.prefName}>Exclude closed questions</div>
            <div className={styles.prefHint}>Always applied — closed questions are never shown (prd.md §14).</div>
          </div>
          <div className={styles.lockedBadge}>Always on</div>
        </div>
        <div className={`${styles.prefRow} ${styles.locked}`}>
          <div className={styles.prefText}>
            <div className={styles.prefName}>Exclude duplicates</div>
            <div className={styles.prefHint}>Always applied — duplicate questions are never shown (prd.md §14).</div>
          </div>
          <div className={styles.lockedBadge}>Always on</div>
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Questions per digest</div>
        <Stepper
          value={form.digest.questions}
          onDecrement={() => update({ digest: { ...form.digest, questions: Math.max(1, form.digest.questions - 1) } })}
          onIncrement={() =>
            update({ digest: { ...form.digest, questions: Math.min(10, form.digest.questions + 1) } })
          }
        />
      </div>

      <div className={styles.card}>
        <div className={styles.cardTitle}>Frequency</div>
        <div className={styles.freqRow}>
          {[1, 3, 7].map((days) => (
            <button
              key={days}
              type="button"
              className={`${styles.freqBtn} ${form.digest.frequency_days === days ? styles.on : ""}`}
              onClick={() => update({ digest: { ...form.digest, frequency_days: days } })}
            >
              {days === 1 ? "Every day" : `Every ${days} days`}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.saveRow}>
        {showSaved && <div className={styles.savedToast}>Saved</div>}
        <button className={styles.btnPrimary} onClick={handleSave} disabled={saving} type="button">
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </main>
  );
}
