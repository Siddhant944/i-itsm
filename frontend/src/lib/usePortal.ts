import { useAuth } from "../auth/AuthContext";
import { portalOf, type Portal } from "../auth/portal";

/** The signed-in user's portal; screens shared by portals use it to build their links. */
export function usePortal(): Portal {
  const { user } = useAuth();
  return user === null ? "employee" : portalOf(user);
}
