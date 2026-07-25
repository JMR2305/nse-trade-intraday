'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Menu, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useState } from 'react';

export function AppHeader() {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isAdmin = pathname.startsWith('/admin');
  const links = isAdmin
    ? [
        { href: '/admin', label: 'Dashboard' },
        { href: '/admin/batches', label: 'Batches' },
        { href: '/admin/documents', label: 'Documents' },
        { href: '/admin/uploads', label: 'Uploads' },
        { href: '/admin/audit', label: 'Audit' },
      ]
    : [
        { href: '/', label: 'Home' },
        { href: '/documents', label: 'Documents' },
        { href: '/batches', label: 'Batches' },
      ];

  return (
    <header className="border-b bg-card sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link href={isAdmin ? '/admin' : '/'} className="flex items-center gap-2 font-semibold text-lg">
            <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-primary-foreground font-bold">
              IT
            </div>
            <span className="hidden sm:inline">Intraday Trade</span>
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden md:flex items-center gap-1">
            {links.map((link) => (
              <Link key={link.href} href={link.href}>
                <Button
                  variant={pathname === link.href ? 'default' : 'ghost'}
                  size="sm"
                  className="text-sm"
                >
                  {link.label}
                </Button>
              </Link>
            ))}
          </nav>

          {/* Admin Link for public users */}
          {!isAdmin && (
            <Link href="/admin" className="hidden md:block">
              <Button variant="ghost" size="sm">
                Admin
              </Button>
            </Link>
          )}

          {/* Mobile Menu Button */}
          <button
            className="md:hidden p-2 hover:bg-muted rounded-lg transition-colors"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
          >
            {mobileMenuOpen ? (
              <X className="h-6 w-6" />
            ) : (
              <Menu className="h-6 w-6" />
            )}
          </button>
        </div>

        {/* Mobile Navigation */}
        {mobileMenuOpen && (
          <nav className="md:hidden pb-4 space-y-2">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
              >
                <Button
                  variant={pathname === link.href ? 'default' : 'ghost'}
                  size="sm"
                  className="w-full justify-start text-sm"
                >
                  {link.label}
                </Button>
              </Link>
            ))}
            {!isAdmin && (
              <Link href="/admin" onClick={() => setMobileMenuOpen(false)}>
                <Button variant="ghost" size="sm" className="w-full justify-start">
                  Admin
                </Button>
              </Link>
            )}
          </nav>
        )}
      </div>
    </header>
  );
}
