import { NextAuthOptions } from "next-auth";
import EmailProvider from "next-auth/providers/email";
import { SQLiteAdapter } from "./sqlite-adapter";

export const authOptions: NextAuthOptions = {
  adapter: SQLiteAdapter(),
  providers: [
    EmailProvider({
      from: process.env.EMAIL_FROM ?? "noreply@example.com",
      sendVerificationRequest: async ({ identifier: email, url }) => {
        const apiKey = process.env.RESEND_API_KEY;
        if (!apiKey) {
          // In development, log the magic link to the console
          console.log(`[NextAuth] Magic link for ${email}: ${url}`);
          return;
        }
        const res = await fetch("https://api.resend.com/emails", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${apiKey}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            from: process.env.EMAIL_FROM ?? "noreply@example.com",
            to: email,
            subject: "Sign in to Email Digest",
            html: `<p>Click the link below to sign in to your Email Digest account:</p>
                   <p><a href="${url}">Sign in</a></p>
                   <p>This link expires in 24 hours and can only be used once.</p>`,
          }),
        });
        if (!res.ok) {
          const body = await res.text();
          throw new Error(`Resend API error: ${body}`);
        }
      },
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    jwt({ token, user }) {
      if (user?.email) {
        token.sub = user.email;
        token.email = user.email;
      }
      return token;
    },
    session({ session, token }) {
      if (session.user && token.sub) {
        (session.user as { id?: string }).id = token.sub;
      }
      return session;
    },
  },
  pages: {
    signIn: "/",
    verifyRequest: "/?verify=1",
  },
  secret: process.env.NEXTAUTH_SECRET,
};
