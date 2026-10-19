import { defineEnvVars } from "@sveltejs/kit/env";

export const variables = defineEnvVars({
  RESEND_API_KEY: {
    schema: (value) => value ?? ""
  },
  RESEND_FROM_EMAIL: {
    schema: (value) => value || "onboarding@resend.dev"
  },
  ORIGIN: {
    schema: (value) => value || undefined
  }
});
