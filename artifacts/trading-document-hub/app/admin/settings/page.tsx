'use client';

import { AppHeader } from '@/components/app-header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Save, AlertCircle } from 'lucide-react';

export default function AdminSettingsPage() {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight mb-2">
            Settings
          </h1>
          <p className="text-muted-foreground">
            Manage application configuration and preferences
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Card>
              <CardHeader>
                <CardTitle>General Settings</CardTitle>
                <CardDescription>
                  Configure basic application settings
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Organization Name</label>
                  <Input placeholder="Enter organization name" defaultValue="Intraday Trade Hub" />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Contact Email</label>
                  <Input type="email" placeholder="admin@example.com" defaultValue="admin@example.com" />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Support URL</label>
                  <Input placeholder="https://support.example.com" />
                </div>
                <div className="space-y-3 pt-4 border-t">
                  <h4 className="font-semibold">API Configuration</h4>
                  <div className="bg-muted p-4 rounded-lg">
                    <p className="text-sm text-muted-foreground mb-3">
                      The application is currently using mock data for demonstration. To connect to a real API, configure the endpoints below.
                    </p>
                    <div className="space-y-2">
                      <label className="text-sm font-medium">Documents API Endpoint</label>
                      <Input placeholder="https://api.example.com/documents" />
                    </div>
                    <div className="space-y-2 mt-4">
                      <label className="text-sm font-medium">Batches API Endpoint</label>
                      <Input placeholder="https://api.example.com/batches" />
                    </div>
                  </div>
                </div>
                <Button className="gap-2 w-full sm:w-auto">
                  <Save className="h-4 w-4" />
                  Save Changes
                </Button>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>System Status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">Database</p>
                  <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                    Connected
                  </Badge>
                </div>
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">API</p>
                  <Badge className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                    Mock Mode
                  </Badge>
                </div>
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">Cache</p>
                  <Badge className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                    Active
                  </Badge>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 text-yellow-600" />
                  Notice
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  This is a demo application with mock data. Connect to your real backend services to see live data in the dashboard.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  );
}
