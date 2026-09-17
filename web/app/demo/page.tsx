import { redirect } from "next/navigation";

import PhoneDemo from "../../components/PhoneDemo";
import { authorizeDemoAccess } from "../../lib/demo-access";

export const dynamic = "force-dynamic";

export default async function DemoPage() {
  const authorization =
    await authorizeDemoAccess();

  if (!authorization.authorized) {
    redirect("/");
  }

  return <PhoneDemo live />;
}