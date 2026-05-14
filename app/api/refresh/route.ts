import { revalidateTag } from "next/cache";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const secret = process.env.REFRESH_SECRET;
  if (secret) {
    const auth = request.headers.get("authorization");
    if (auth !== `Bearer ${secret}`) {
      return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
    }
  }
  revalidateTag("zillow", "default");
  revalidateTag("fred", "default");
  return NextResponse.json({ ok: true, refreshed: ["zillow", "fred"] });
}

export async function GET(request: Request) {
  return POST(request);
}
