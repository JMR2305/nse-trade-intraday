'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { AuditLog } from '@/lib/types';
import { auditService } from '@/lib/services';
import { ActivityList } from '@/components/activity-list';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { AlertCircle } from 'lucide-react';

export default function AdminAuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadLogs = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await auditService.getAll();
        setLogs(data.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime()));
      } catch (err) {
        setError('Failed to load audit logs');
        console.error('[v0] Error loading audit logs:', err);
      } finally {
        setLoading(false);
      }
    };
    loadLogs();
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
        <div className="mb-8">
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-2">
            Audit Log
          </h1>
          <p className="text-muted-foreground text-sm md:text-base">
            Track all system activities and changes
          </p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-destructive/10 border border-destructive rounded-lg flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-destructive">{error}</p>
              <p className="text-sm text-destructive/80 mt-1">
                Please try refreshing the page or contact support if the problem persists.
              </p>
            </div>
          </div>
        )}

        {loading ? (
          <Card>
            <CardHeader>
              <Skeleton className="h-6 w-32 mb-2" />
              <Skeleton className="h-4 w-48" />
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            </CardContent>
          </Card>
        ) : logs.length === 0 ? (
          <Card>
            <CardContent className="pt-12 pb-12 text-center">
              <p className="text-muted-foreground">No audit logs found</p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Activity History</CardTitle>
              <CardDescription>
                Showing {logs.length} recent activities
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ActivityList logs={logs} />
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
