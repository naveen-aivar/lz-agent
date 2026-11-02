import type { Metadata } from 'next';

import './globals.css';

export const metadata: Metadata = {
  title: 'Migration and Modernization Agents | Ingram Micro',
  description: 'The Ingram Micro Migration and Modernization agents in one place: sign in once and switch between agents.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full antialiased">{children}</body>
    </html>
  );
}
