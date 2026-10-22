// ENGR-07: API and panel load test (k6). Launch design target: 500 companies, 99.9 % availability (SDD §22-23).
//   k6 run -e BASE=https://staging.example.com -e PASSWORD=... -e COMPANIES=10 -e VUS=50 deploy/loadtest/api.js
// Users are the loadtest-<n>@example.com owners made by setup.py. Every virtual user acts as one of them: the API
// calls a company's team makes all day (leads, dashboard numbers, calendar, billing) plus the public website.
import http from "k6/http";
import { check, group, sleep } from "k6";

const BASE = __ENV.BASE || "https://localhost";
const COMPANIES = parseInt(__ENV.COMPANIES || "10");
const VUS = parseInt(__ENV.VUS || "50");

export const options = {
  insecureSkipTLSVerify: true, // CI / staging self-signed certificates only
  hosts: __ENV.HOST_IP ? { localhost: __ENV.HOST_IP } : {}, // k6 in Docker against a server on the host machine
  scenarios: {
    team: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: __ENV.RAMP || "30s", target: VUS },
        { duration: __ENV.HOLD || "2m", target: VUS },
        { duration: "15s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"], // < 1 % errors
    "http_req_duration{kind:api}": ["p(95)<800"], // panel / app API
    "http_req_duration{kind:page}": ["p(95)<1500"], // server-rendered website page
    checks: ["rate>0.99"],
  },
};

export function setup() {
  const tokens = [];
  for (let n = 1; n <= COMPANIES; n++) {
    const r = http.post(
      `${BASE}/api/v1/auth/app/v1/auth/login`,
      JSON.stringify({ email: `loadtest-${n}@example.com`, password: __ENV.PASSWORD }),
      { headers: { "Content-Type": "application/json" } },
    );
    check(r, { "login ok": (res) => res.status === 200 });
    tokens.push(r.json("meta.access_token"));
  }
  return { tokens };
}

const API = [
  "/api/v1/company/",
  "/api/v1/crm/leads/",
  "/api/v1/crm/leads/?search=Ra",
  "/api/v1/analytics/?range=7d&parts=kpis,series",
  "/api/v1/calendar/appointments/",
  "/api/v1/billing/",
  "/api/v1/notifications/",
];

export default function (data) {
  const token = data.tokens[(__VU - 1) % data.tokens.length];
  const params = { headers: { Authorization: `Bearer ${token}` }, tags: { kind: "api" } };
  group("company team (API)", () => {
    for (const path of API) {
      const r = http.get(`${BASE}${path}`, Object.assign({}, params, { tags: { kind: "api", name: path.split("?")[0] } }));
      check(r, { [`${path} 200`]: (res) => res.status === 200 });
    }
  });
  group("website", () => {
    const r = http.get(`${BASE}/`, { tags: { kind: "page", name: "/" } });
    check(r, { "home 200": (res) => res.status === 200 });
  });
  sleep(1);
}
