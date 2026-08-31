import { fixtureRepository } from "@/data/repositories/fixture-repository";
import { HttpInvestigatorRepository } from "@/data/repositories/http-investigator-repository";
import type { InvestigatorRepository } from "@/data/repositories/investigator-repository";

export function createRuntimeRepository(): InvestigatorRepository {
  return process.env.NEXT_PUBLIC_AMEX_DATA_MODE === "fixture"
    ? fixtureRepository
    : new HttpInvestigatorRepository();
}

export const runtimeRepository = createRuntimeRepository();
