// Scout-mode editable form for one segment (ARCHITECTURE.md §7.3, BRIEF panel 2). Every field
// writes straight into the localStorage overlay (state/overlay.ts) on commit (`change`, i.e. on
// blur/Enter — never on every keystroke, so a re-render triggered by the write never yanks focus
// out from under someone mid-sentence). main.ts subscribes to `overlayStore` and re-renders every
// panel after each write, so nothing here needs to trigger its own re-render.

import {
  CHARACTERS,
  SCOUTING_VERDICTS,
  SEGMENT_STATUSES,
  STATUS_META,
  type Character,
  type ScoutingVerdict,
  type SegmentFeature,
  type Status,
} from '../data/types.ts';
import { titleCase } from '../lib/format.ts';
import {
  getAuthor,
  overlayStore,
  setAuthor,
  withoutSegment,
  withScoutingEntryAppended,
  withSegmentEdit,
} from '../state/overlay.ts';
import { el } from './ui.ts';

function labeled(labelText: string, control: HTMLElement): HTMLElement {
  const row = el('label', 'form-row');
  row.append(el('span', 'form-label', labelText), control);
  return row;
}

function selectOf<T extends string>(values: readonly T[], current: T, format = titleCase): HTMLSelectElement {
  const select = document.createElement('select');
  for (const v of values) select.appendChild(new Option(format(v), v));
  select.value = current;
  return select;
}

/** Splits a textarea's value into a trimmed, non-empty-line string array — the "list" editor for
 * `water_points`/`hazards`/`open_questions`: one item per line, kept deliberately simple (BRIEF
 * "Prefer clarity over cleverness"). */
function linesToList(value: string): string[] {
  return value
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
}

function listTextarea(label: string, values: readonly string[] | undefined, onCommit: (list: string[]) => void): HTMLElement {
  const textarea = document.createElement('textarea');
  textarea.rows = 3;
  textarea.value = (values ?? []).join('\n');
  textarea.placeholder = 'One per line';
  textarea.addEventListener('change', () => onCommit(linesToList(textarea.value)));
  return labeled(label, textarea);
}

export function renderScoutForm(container: HTMLElement, segment: SegmentFeature): void {
  const id = segment.properties.id;
  const props = segment.properties;

  container.replaceChildren();
  container.appendChild(el('h3', 'form-heading', 'Scouting form'));

  function patch(fields: Parameters<typeof withSegmentEdit>[2]): void {
    overlayStore.set(withSegmentEdit(overlayStore.getState(), id, fields));
  }

  const form = el('div', 'scout-form');

  const statusSelect = selectOf(SEGMENT_STATUSES, props.status, (s) => STATUS_META[s as Status].label);
  statusSelect.addEventListener('change', () => patch({ status: statusSelect.value as Status }));
  form.appendChild(labeled('Status', statusSelect));

  const characterSelect = selectOf(CHARACTERS, props.character);
  characterSelect.addEventListener('change', () => patch({ character: characterSelect.value as Character }));
  form.appendChild(labeled('Character', characterSelect));

  const habInput = document.createElement('input');
  habInput.type = 'number';
  habInput.min = '0';
  habInput.step = '0.1';
  habInput.value = String(props.est_hab_km);
  habInput.addEventListener('change', () => {
    const value = Number(habInput.value);
    if (Number.isFinite(value) && value >= 0) patch({ est_hab_km: value });
  });
  form.appendChild(labeled('Est. hike-a-bike (km)', habInput));

  const difficultyInput = document.createElement('input');
  difficultyInput.type = 'number';
  difficultyInput.min = '1';
  difficultyInput.max = '5';
  difficultyInput.value = String(props.difficulty);
  difficultyInput.addEventListener('change', () => {
    const value = Math.round(Number(difficultyInput.value));
    if (value >= 1 && value <= 5) patch({ difficulty: value });
  });
  form.appendChild(labeled('Difficulty (1-5)', difficultyInput));

  const remotenessInput = document.createElement('input');
  remotenessInput.type = 'number';
  remotenessInput.min = '1';
  remotenessInput.max = '5';
  remotenessInput.value = String(props.remoteness);
  remotenessInput.addEventListener('change', () => {
    const value = Math.round(Number(remotenessInput.value));
    if (value >= 1 && value <= 5) patch({ remoteness: value });
  });
  form.appendChild(labeled('Remoteness (1-5)', remotenessInput));

  form.appendChild(listTextarea('Water points', props.water_points, (list) => patch({ water_points: list })));

  const resupplyInput = document.createElement('textarea');
  resupplyInput.rows = 2;
  resupplyInput.value = props.resupply_notes ?? '';
  resupplyInput.addEventListener('change', () => patch({ resupply_notes: resupplyInput.value }));
  form.appendChild(labeled('Resupply notes', resupplyInput));

  form.appendChild(listTextarea('Hazards', props.hazards, (list) => patch({ hazards: list })));

  const culturalInput = document.createElement('textarea');
  culturalInput.rows = 2;
  culturalInput.value = props.cultural_notes ?? '';
  culturalInput.addEventListener('change', () => patch({ cultural_notes: culturalInput.value }));
  form.appendChild(labeled('Cultural notes', culturalInput));

  form.appendChild(
    listTextarea('Open questions', props.open_questions, (list) => patch({ open_questions: list })),
  );

  container.appendChild(form);

  // --- Add a scouting entry ------------------------------------------------------------------
  container.appendChild(el('h3', 'form-heading', 'Add scouting entry'));
  const entryForm = el('div', 'scout-form');

  const dateInput = document.createElement('input');
  dateInput.type = 'date';
  dateInput.value = new Date().toISOString().slice(0, 10);
  entryForm.appendChild(labeled('Date', dateInput));

  const teamInput = document.createElement('input');
  teamInput.type = 'text';
  teamInput.value = getAuthor();
  teamInput.placeholder = 'Initials, e.g. RC';
  entryForm.appendChild(labeled('Team', teamInput));

  const verdictSelect = selectOf(SCOUTING_VERDICTS, 'go');
  entryForm.appendChild(labeled('Verdict', verdictSelect));

  const notesInput = document.createElement('textarea');
  notesInput.rows = 2;
  notesInput.placeholder = 'What did you find?';
  entryForm.appendChild(labeled('Notes', notesInput));

  const addStatus = el('p', 'state state-error');
  addStatus.hidden = true;

  const addButton = el('button', 'btn btn-accent', 'Add entry');
  addButton.type = 'button';
  addButton.addEventListener('click', () => {
    const date = dateInput.value;
    const team = teamInput.value.trim();
    if (!date || !team) {
      addStatus.textContent = 'Date and team are required.';
      addStatus.hidden = false;
      return;
    }
    setAuthor(team);
    overlayStore.set(
      withScoutingEntryAppended(overlayStore.getState(), id, {
        date,
        team,
        verdict: verdictSelect.value as ScoutingVerdict,
        notes: notesInput.value.trim() || undefined,
      }),
    );
  });
  entryForm.appendChild(addButton);
  entryForm.appendChild(addStatus);
  container.appendChild(entryForm);

  // --- Discard this segment's local edits ----------------------------------------------------
  const discardRow = el('div', 'button-row');
  const discardButton = el('button', 'btn', 'Discard local edits for this segment');
  discardButton.type = 'button';
  discardButton.addEventListener('click', () => {
    if (!confirm('Discard local scouting edits for this segment? This cannot be undone.')) return;
    overlayStore.set(withoutSegment(overlayStore.getState(), id));
  });
  discardRow.appendChild(discardButton);
  container.appendChild(discardRow);
}
