import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname === '/' || request.nextUrl.pathname === '/v7-operations') {
    return NextResponse.redirect(new URL('/trading-operations', request.url));
  }
  // Backward compat: old URL still works
  if (request.nextUrl.pathname === '/training-operations') {
    return NextResponse.redirect(new URL('/trading-operations', request.url));
  }
}

export const config = {
  matcher: ['/', '/v7-operations', '/training-operations'],
};
