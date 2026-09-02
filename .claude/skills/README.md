# Claude Code Skills

이 디렉터리에는 [Superpowers](https://github.com/obra/superpowers) 스킬 모음이 설치되어 있습니다.

- **출처**: https://github.com/obra/superpowers
- **버전**: v6.3.0 (commit `b36e082`)
- **라이선스**: `SUPERPOWERS_LICENSE` 참고 (MIT, © Jesse Vincent)

## 사용법

각 스킬은 하위 디렉터리의 `SKILL.md`에 정의되어 있습니다. Claude Code가
작업 중 관련 스킬을 자동으로 인식해 활용하며, 대화에서 스킬 이름으로
직접 호출할 수도 있습니다.

## 포함된 스킬

| 스킬 | 설명 |
|------|------|
| `using-superpowers` | 스킬 검색·활용 방식을 안내하는 진입점 스킬 |
| `brainstorming` | 아이디어 발산 및 스펙 구체화 |
| `writing-plans` | 정확한 파일 경로까지 담은 상세 계획 작성 |
| `executing-plans` | 작성된 계획 실행 |
| `test-driven-development` | RED-GREEN-REFACTOR 기반 TDD |
| `systematic-debugging` | 근본 원인 분석 중심의 체계적 디버깅 |
| `verification-before-completion` | 완료 전 검증 |
| `requesting-code-review` | 코드 리뷰 요청 |
| `receiving-code-review` | 코드 리뷰 반영 |
| `subagent-driven-development` | 서브에이전트 기반 개발 |
| `dispatching-parallel-agents` | 병렬 에이전트 실행 |
| `using-git-worktrees` | git worktree 활용 |
| `finishing-a-development-branch` | 개발 브랜치 마무리 |
| `writing-skills` | 새 스킬 작성 |

## 업데이트

상위 저장소에서 최신 스킬을 다시 가져오려면:

```bash
git clone --depth 1 https://github.com/obra/superpowers.git
cp -R superpowers/skills/. .claude/skills/
```

> 개인 Claude Code CLI 전역에 플러그인으로 설치하려면
> `/plugin install superpowers@claude-plugins-official` 를 사용하세요.
