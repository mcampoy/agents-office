// API URLs with the chosen project. The project goes in the page URL (?p=<id>), so each browser tab
// stays fixed on one project and can be bookmarked.

let project: string | null = new URLSearchParams(window.location.search).get('p');

export interface ProjectListing {
  id: string;
  name: string;
  last_event: string | null;
  active: number;
}

export function currentProject(): string | null {
  return project;
}

/** API path with ?project= (or &project=) if one is chosen. */
export function api(path: string): string {
  if (!project) return `./api/${path}`;
  return `./api/${path}${path.includes('?') ? '&' : '?'}project=${encodeURIComponent(project)}`;
}

/** Project list. If the URL does not choose one, it fixes the one with the latest activity (the first). */
export async function loadProjects(): Promise<ProjectListing[]> {
  try {
    const r = await fetch('./api/projects', { cache: 'no-store' });
    const list = ((await r.json()) as { projects: ProjectListing[] }).projects ?? [];
    if (!project && list.length > 0) project = list[0].id;
    return list;
  } catch {
    return [];
  }
}

/** Switches project by reloading the page with ?p=<id> (the whole floor state is per project). */
export function goToProject(id: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set('p', id);
  window.location.href = url.toString();
}
