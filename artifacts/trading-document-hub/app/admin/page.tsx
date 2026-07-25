'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { StatCard } from '@/components/stat-card';
import { ActivityList } from '@/components/activity-list';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { DashboardStats } from '@/lib/types';
import { dashboardService } from '@/lib/services';
import { FileText, FolderOpen, Upload, TrendingUp } from 'lucide-react';

export default function AdminDashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadStats = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await dashboardService.getStats();
        setStats(data);
      } catch (err) {
        setError('Failed to load dashboard');
        console.error('[v0] Error loading dashboard:', err);
      } finally {
        setLoading(false);
      }
    };
    loadStats();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <AppHeader />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-lg" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Skeleton className="lg:col-span-2 h-96 rounded-lg" />
            <Skeleton className="h-96 rounded-lg" />
          </div>
        </main>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="min-h-screen bg-background">
        <AppHeader />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
          <div className="p-8 bg-destructive/10 border border-destructive rounded-lg text-center">
            <p className="text-destructive font-medium">{error || 'Failed to load dashboard'}</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
        <div className="mb-8">
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-2">
            Admin Dashboard
          </h1>
          <p className="text-muted-foreground text-sm md:text-base">
            Overview of documents, batches, and uploads
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6 mb-8">
          <StatCard
            title="Total Documents"
            value={stats.totalDocuments}
            icon={FileText}
            description="All documents in system"
          />
          <StatCard
            title="Total Batches"
            value={stats.totalBatches}
            icon={FolderOpen}
            description="Document collections"
          />
          <StatCard
            title="Total Uploads"
            value={stats.totalUploads}
            icon={Upload}
            description="Files uploaded"
          />
          <StatCard
            title="Published"
            value={stats.publishedDocuments}
            icon={TrendingUp}
            description="Public documents"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle>Recent Activity</CardTitle>
                <CardDescription>Latest document and batch activities</CardDescription>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <ActivityList logs={stats.recentActivity} />
              </CardContent>
            </Card>
          </div>

          <div>
            <Card>
              <CardHeader>
                <CardTitle>Quick Stats</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between items-center pb-4 border-b">
                  <span className="text-sm text-muted-foreground">Pending Uploads</span>
                  <span className="text-lg md:text-xl font-bold">
                    {stats.pendingUploads}
                  </span>
                </div>
                <div className="flex justify-between items-center pb-4 border-b">
                  <span className="text-sm text-muted-foreground">Avg per Batch</span>
                  <span className="text-lg md:text-xl font-bold">
                    {stats.totalBatches > 0
                      ? (stats.totalDocuments / stats.totalBatches).toFixed(1)
                      : 0}
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-muted-foreground">Publication Rate</span>
                  <span className="text-lg md:text-xl font-bold">
                    {stats.totalDocuments > 0
                      ? `${((stats.publishedDocuments / stats.totalDocuments) * 100).toFixed(0)}%`
                      : '0%'}
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
