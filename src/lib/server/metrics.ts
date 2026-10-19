export interface DashboardMetrics {
  pagesCollected: number;
  pagesIndexed: number;
  pdfsDiscovered: number;
  pdfsDownloaded: number;
}

export async function getDashboardMetrics(): Promise<DashboardMetrics> {
  return {
    pagesCollected: 0,
    pagesIndexed: 0,
    pdfsDiscovered: 0,
    pdfsDownloaded: 0
  };
}
