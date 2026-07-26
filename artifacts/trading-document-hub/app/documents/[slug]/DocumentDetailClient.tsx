'use client';

import { useParams } from 'next/navigation';
import { useState } from 'react';
import { AppHeader } from '@/components/app-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { documentService } from '@/lib/services';
import { Copy, Download, Link as LinkIcon, FileDown, Zap } from 'lucide-react';

export default function DocumentDetailClient() {
  const params = useParams();
  const slug = params.slug as string;
  const doc = documentService.getDocumentBySlug(slug);
  const [copied, setCopied] = useState(false);
  const [kimiPrompt, setKimiPrompt] = useState('');

  if (!doc) {
    return (
      <div className="min-h-screen bg-background">
        <AppHeader />
        <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex items-center justify-center py-12">
            <div className="text-muted-foreground">Document not found</div>
          </div>
        </main>
      </div>
    );
  }

  const shareUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}/documents/${doc.slug}`;
  
  const generateKimiPrompt = () => {
    const prompt = `Please analyze and summarize this research document:

Title: ${doc.title}
Type: ${doc.type}
Date: ${doc.publishedDate}
Author: ${doc.author}
Description: ${doc.description}

Tags: ${doc.tags.join(', ')}
Pages: ${doc.pageCount}

Please provide:
1. Executive summary
2. Key findings
3. Important metrics or data
4. Recommendations or conclusions
5. Relevance to intraday trading strategies`;
    
    setKimiPrompt(prompt);
    return prompt;
  };

  const handleCopyLink = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadManifest = () => {
    const manifest = {
      document: {
        title: doc.title,
        type: doc.type,
        url: shareUrl,
        publishedDate: doc.publishedDate,
        author: doc.author,
        description: doc.description,
        tags: doc.tags,
        pageCount: doc.pageCount,
      },
      downloadedAt: new Date().toISOString(),
    };

    const element = document.createElement('a');
    element.setAttribute('href', `data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(manifest, null, 2))}`);
    element.setAttribute('download', `${doc.slug}-manifest.json`);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Badge variant="outline">{doc.type}</Badge>
                {doc.isPublished && <Badge className="bg-green-100 text-green-900">Published</Badge>}
              </div>
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight mb-2">{doc.title}</h1>
              <p className="text-muted-foreground text-lg">{doc.description}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 mb-6">
            {doc.tags.map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
            <div className="p-3 bg-muted rounded-lg">
              <div className="text-xs text-muted-foreground mb-1">Author</div>
              <div className="font-medium">{doc.author}</div>
            </div>
            <div className="p-3 bg-muted rounded-lg">
              <div className="text-xs text-muted-foreground mb-1">Published</div>
              <div className="font-medium">{doc.publishedDate}</div>
            </div>
            <div className="p-3 bg-muted rounded-lg">
              <div className="text-xs text-muted-foreground mb-1">Pages</div>
              <div className="font-medium">{doc.pageCount}</div>
            </div>
            <div className="p-3 bg-muted rounded-lg">
              <div className="text-xs text-muted-foreground mb-1">Type</div>
              <div className="font-medium capitalize">{doc.type}</div>
            </div>
          </div>

          <Card className="mb-8">
            <CardHeader>
              <CardTitle className="text-lg">Share & Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-col gap-3">
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={handleCopyLink}
                >
                  <LinkIcon className="w-4 h-4 mr-2" />
                  {copied ? 'Link copied!' : 'Copy link to document'}
                </Button>

                <Dialog>
                  <DialogTrigger asChild>
                    <Button
                      variant="outline"
                      className="w-full justify-start"
                      onClick={generateKimiPrompt}
                    >
                      <Zap className="w-4 h-4 mr-2" />
                      Copy prompt for Kimi
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="max-w-2xl max-h-96 overflow-y-auto">
                    <DialogHeader>
                      <DialogTitle>Kimi Analysis Prompt</DialogTitle>
                      <DialogDescription>Copy this prompt to analyze the document with Kimi</DialogDescription>
                    </DialogHeader>
                    <div className="bg-muted p-4 rounded-lg mb-4 max-h-64 overflow-y-auto">
                      <pre className="whitespace-pre-wrap text-sm font-mono text-foreground">
                        {kimiPrompt}
                      </pre>
                    </div>
                    <Button
                      onClick={() => {
                        navigator.clipboard.writeText(kimiPrompt);
                        alert('Prompt copied to clipboard!');
                      }}
                      className="w-full"
                    >
                      <Copy className="w-4 h-4 mr-2" />
                      Copy to Clipboard
                    </Button>
                  </DialogContent>
                </Dialog>

                <Button
                  variant="outline"
                  className="w-full justify-start"
                  onClick={handleDownloadManifest}
                >
                  <Download className="w-4 h-4 mr-2" />
                  Download manifest
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Document Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <h3 className="font-semibold mb-2">Description</h3>
                <p className="text-muted-foreground leading-relaxed">{doc.description}</p>
              </div>
              <div>
                <h3 className="font-semibold mb-2">Tags</h3>
                <div className="flex flex-wrap gap-2">
                  {doc.tags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="pt-4 border-t">
                <p className="text-xs text-muted-foreground">
                  Document ID: {doc.id}
                </p>
                <p className="text-xs text-muted-foreground">
                  Last updated: {doc.publishedDate}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
