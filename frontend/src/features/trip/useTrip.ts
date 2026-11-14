import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getTripOptions } from "../../client/@tanstack/react-query.gen";
import type { TripOut } from "../../client/types.gen";

/**
 * 行程（一張保單）的快取（ADR-0029）：行程頁的所有動作都回行程頁內容，直接寫回這份快取，
 * 畫面一次更新；問答等回應是舊快照的動作改成 `refresh` 重新讀取。
 */
export function useTrip(policyId: string) {
  const queryClient = useQueryClient();
  const options = getTripOptions({ path: { policy_id: policyId } });
  const query = useQuery({ ...options, retry: false }); // 找不到（404）不重試，直接顯示提示
  const setTrip = (trip: TripOut) => queryClient.setQueryData(options.queryKey, trip);
  const refresh = () => queryClient.invalidateQueries({ queryKey: options.queryKey });
  return { ...query, setTrip, refresh };
}
