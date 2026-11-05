import { useQuery } from "@tanstack/react-query";
import { googleGrantStatusOptions } from "../../client/@tanstack/react-query.gen";

/**
 * 目前的 Google 授權：drive、gmail 各自現在能不能用（ADR-0020）。
 * 後端會實際向 Google 確認授權沒有過期，所以每次打開頁面都重新查，不沿用舊結果。
 * enabled=false 時不查（例如沒開 Google 登入、或是用測試登入）。
 */
export function useGoogleGrant(enabled = true) {
  return useQuery({ ...googleGrantStatusOptions(), enabled, staleTime: 0, retry: false });
}
