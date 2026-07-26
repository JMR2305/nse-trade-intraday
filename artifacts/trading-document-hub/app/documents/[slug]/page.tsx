// Server component wrapper — required for generateStaticParams with output:'export'.
// The actual UI lives in DocumentDetailClient (a 'use client' component).
import DocumentDetailClient from './DocumentDetailClient';

// Pre-render one HTML file per known document slug.
// Unknown slugs will be handled client-side via the artifact rewrite rule.
export async function generateStaticParams() {
  return [
    { slug: 'morning-market-analysis-tech-sector' },
    { slug: 'intraday-trading-signals-report' },
    { slug: 'earnings-report-update' },
    { slug: 'weekly-market-research-summary' },
  ];
}

export default function DocumentDetailPage() {
  return <DocumentDetailClient />;
}
