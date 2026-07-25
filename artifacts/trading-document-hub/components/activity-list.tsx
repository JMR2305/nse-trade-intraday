'use client';

import { AuditLog } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { formatDistanceToNow } from 'date-fns';

interface ActivityListProps {
  logs: AuditLog[];
}

const actionColors: Record<string, string> = {
  created: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  updated: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  deleted: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  published: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  uploaded: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
};

export function ActivityList({ logs }: ActivityListProps) {
  return (
    <div className="space-y-4">
      {logs.length === 0 ? (
        <p className="text-sm text-muted-foreground py-8 text-center">
          No activity yet
        </p>
      ) : (
        logs.map((log) => (
          <div key={log.id} className="flex items-start gap-4 pb-4 border-b last:border-0">
            <div className="flex-shrink-0 mt-1">
              <Badge
                className={`capitalize ${actionColors[log.action] || 'bg-gray-100 text-gray-800'}`}
              >
                {log.action}
              </Badge>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium capitalize">
                {log.action} {log.entityType}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                by <span className="font-medium">{log.userId}</span>
              </p>
              <p className="text-xs text-muted-foreground">
                {formatDistanceToNow(log.timestamp, { addSuffix: true })}
              </p>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
