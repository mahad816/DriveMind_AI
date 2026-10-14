import assert from "node:assert/strict";
import { mkdir, writeFile, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import http from "node:http";
import { once } from "node:events";
import test from "node:test";

// First run `node /tests/image-smoke.test.mjs --fixtures` BEFORE starting Next
// (Next inventories public assets at startup). Then, inside that disposable image:
// DEPLOYMENT_TEST_URL=http://127.0.0.1:3000 node --test /tests/image-smoke.test.mjs
// Assets are synthetic and removed after the run; never run against live storage.
const require = createRequire(`${process.cwd()}/package.json`);
const sharp = require("sharp");
const base = process.env.DEPLOYMENT_TEST_URL;
const fixturePath = "/__security_image_fixture";
const directory = `${process.cwd()}/public${fixturePath}`;

if (process.argv.includes("--fixtures")) {
  await mkdir(directory, { recursive: true });
  const pixels = { create: { width: 64, height: 64, channels: 3, background: "#336699" } };
  await writeFile(`${directory}/valid.png`, await sharp(pixels).png().toBuffer());
  await writeFile(`${directory}/valid.avif`, await sharp(pixels).avif().toBuffer());
  await writeFile(`${directory}/invalid.png`, "not an image");
  await writeFile(`${directory}/unsafe.svg`, '<svg xmlns="http://www.w3.org/2000/svg"><script>synthetic()</script></svg>');
} else {
  if (!base || !["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname)) {
    throw new Error("Image smoke requires an explicit disposable loopback server");
  }
  test("unsafe native decoder versions fail closed", () => {
    const { isAvifDecodeSafe } = require("next/dist/server/image-optimizer.js");
    for (const version of [null, "unknown", "1.21.2", "1.23.1"]) {
      assert.equal(isAvifDecodeSafe(version), false);
    }
    assert.equal(isAvifDecodeSafe(sharp.versions.heif), true);
  });
  test("custom production server preserves private API and callback security headers", async () => {
    const backend = new URL(process.env.BACKEND_URL);
    assert.equal(backend.hostname, "127.0.0.1", "requires a disposable synthetic backend");
    let submissions = 0;
    const mock = http.createServer(async (request, response) => {
      if (request.url.startsWith("/api/v1/auth/session/google/callback?")) {
        response.writeHead(303, {
          location: "https://frontend.example/settings?login=success",
          "set-cookie": ["__Host-drivemind-session=synthetic; Path=/; Secure; HttpOnly; SameSite=Lax", "binding=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"],
        });
        response.end();
        return;
      }
      if (request.headers.origin !== "https://frontend.example" || request.headers["x-csrf-token"] !== "synthetic-csrf") {
        response.writeHead(403); response.end('{"detail":"Rejected"}'); return;
      }
      assert.equal(request.headers.cookie, "__Host-drivemind-session=synthetic");
      let body = "";
      for await (const chunk of request) body += chunk;
      assert.equal(JSON.parse(body).question, "synthetic private question");
      submissions++;
      response.writeHead(202, { "content-type": "application/json" });
      response.end('{"status":"RUNNING"}');
    });
    mock.listen(Number(backend.port), "127.0.0.1");
    await once(mock, "listening");
    try {
      const callback = await fetch(`${base}/api/v1/auth/session/google/callback?code=synthetic&state=synthetic`, { redirect: "manual" });
      assert.equal(callback.status, 303);
      assert.equal(callback.headers.getSetCookie().length, 2);
      assert.match(callback.headers.getSetCookie()[0], /Secure; HttpOnly; SameSite=Lax/);
      assert.doesNotMatch(callback.headers.getSetCookie()[0], /Domain=/);
      const headers = { Origin: "https://frontend.example", "X-CSRF-Token": "synthetic-csrf", Cookie: "__Host-drivemind-session=synthetic" };
      const submission = await fetch(`${base}/api/v1/conversations/opaque/turns`, {
        method: "POST", headers, body: JSON.stringify({ question: "synthetic private question" }),
      });
      assert.equal(submission.status, 202);
      assert.equal((await submission.json()).status, "RUNNING");
      assert.equal(submission.headers.get("cache-control"), "private, no-store");
      const rejected = await fetch(`${base}/api/v1/conversations/opaque/turns`, {
        method: "POST", headers: { ...headers, Origin: "https://foreign.example" }, body: "{}",
      });
      assert.equal(rejected.status, 403);
      assert.equal(rejected.headers.get("cache-control"), "private, no-store");
      assert.equal(submissions, 1);
    } finally {
      await new Promise((resolve) => mock.close(resolve));
    }
  });
  test("patched native library and actual Next image handler", async (t) => {
    assert.equal(require("next/package.json").version, "15.5.27");
    assert.equal(sharp.versions.sharp, "0.35.5");
    assert.equal(sharp.versions.rsvg, "2.63.2");
    t.after(() => rm(directory, { recursive: true, force: true }));
    const optimize = (url, width = "64") => fetch(
      `${base}/_next/image?${new URLSearchParams({ url, w: width, q: "75" })}`,
      { signal: AbortSignal.timeout(15_000) },
    );

    await t.test("PNG optimization succeeds with patched sharp", async () => {
      const response = await optimize(`${fixturePath}/valid.png`);
      assert.equal(response.status, 200);
      assert.match(response.headers.get("content-type"), /^image\//);
      assert.equal((await sharp(Buffer.from(await response.arrayBuffer())).metadata()).width, 64);
    });
    await t.test("AVIF optimization uses the verified safe decoder", async () => {
      const original = await fetch(`${base}${fixturePath}/valid.avif`);
      assert.equal(original.status, 200);
      assert.equal((await sharp(Buffer.from(await original.arrayBuffer())).metadata()).format, "heif");
      const response = await optimize(`${fixturePath}/valid.avif`, "32");
      assert.equal(response.status, 200);
      assert.equal((await sharp(Buffer.from(await response.arrayBuffer())).metadata()).width, 32);
    });
    await t.test("SVG and invalid image bytes are rejected", async () => {
      for (const file of ["unsafe.svg", "invalid.png"]) {
        assert.equal((await optimize(`${fixturePath}/${file}`)).status, 400);
      }
      await assert.rejects(sharp(Buffer.from("not an image")).metadata());
    });
    await t.test("invalid image size is rejected", async () => {
      assert.equal((await optimize(`${fixturePath}/valid.png`, "13")).status, 400);
    });
    await t.test("unapproved remote image cannot access a private service", async () => {
      let hits = 0;
      const sentinel = http.createServer((_req, res) => { hits++; res.end("private sentinel"); });
      sentinel.listen(0, "127.0.0.1");
      await once(sentinel, "listening");
      try {
        const response = await optimize(`http://127.0.0.1:${sentinel.address().port}/private`);
        assert.equal(response.status, 400);
        assert.equal(hits, 0);
      } finally {
        await new Promise((resolve) => sentinel.close(resolve));
      }
    });
  });
}
