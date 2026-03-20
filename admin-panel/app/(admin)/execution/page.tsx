"use client";
import { useEffect } from "react";

export default function ExecutionPage() {
  useEffect(() => {
    window.location.href = "https://bahamut.ai/execution";
  }, []);

  return (
    <div className="p-6 text-bah-muted text-center py-20">
      <p>Redirecting to Execution Engine...</p>
      <a href="https://bahamut.ai/execution" className="text-bah-cyan hover:underline mt-2 inline-block">
        Click here if not redirected
      </a>
    </div>
  );
}
