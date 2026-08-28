# Lab 1 Report: Room Booking Service

**Course:** CMU 17-214, Fall 2026

**Date:** August 28, 2026

**Repository:** [qfhu0ng/f26-lab01](https://github.com/qfhu0ng/f26-lab01)

**Code revision tested:** `95b8007779ec5e232fac53d29aa62c471fc0c88e`

**AI assistance:** OpenAI Codex desktop app, model `gpt-5.6-sol`, assisted with diagnosis, implementation, tests, explanations, and drafting this report.

## 1. Objective and result

This lab involved diagnosing a defect across a layered Java application, implementing booking cancellation with waitlist promotion, and evaluating an incorrect availability query. The implementation and regression tests are complete on `main`; the six implementation/documentation commits have been pushed to the fork. A fresh test run passed all 23 tests.

This report records the work and its evidence. It does not certify TA checkoff. The [Lab 1 handout](https://github.com/CMU-17-214/f2026/blob/main/labs/lab01.md) requires demonstrating all three milestones during the August 28 recitation and showing an exported agent session locally. It does not list a written report as an additional deliverable.

## 2. System and environment

The application separates data rules, service operations, and storage:

| Layer | Main components | Responsibility |
| --- | --- | --- |
| Domain | `TimeInterval`, `Room`, `User`, `Booking`, `WaitlistEntry` | Represent entities and define time overlap. |
| Service | `BookingService`, `BookingResult` | Confirm or waitlist requests, cancel bookings, promote waiters, and report availability. |
| Repository | `BookingStore`, `InMemoryBookingStore` | Store and retrieve bookings and waitlist entries. |

The central invariant is that confirmed bookings for the same room must not overlap. Different rooms may be booked for identical intervals. Times are integer minutes since midnight, and intervals are half-open: `[start, end)`. Consequently, `[600, 660)` and `[660, 720)` may both be confirmed for one room.

The environment used for the final run was macOS 14.6.1 on ARM64, Homebrew OpenJDK 26.0.2.1, and Maven 3.9.16. The Maven project targets Java 21 through `maven.compiler.release`; the installed runtime version and the compilation target are different settings. Tests use JUnit 5.10.2 and Maven Surefire 3.2.5.

## 3. Milestone 1: trace and fix the failing test

### Symptom and root cause

The initial suite ran 10 tests with one failure: `sameSlotInDifferentRoomsAreBothConfirmed`. After Alice booked room A for `[600, 660)`, Bob's request for room B over the same interval returned `Waitlisted` instead of `Confirmed`.

The failing assertion was in a service test, but the defect was in `InMemoryBookingStore.bookingsForRoom`. Its original implementation returned every booking:

```java
return List.copyOf(bookings);
```

`BookingService.book` reasonably treated those results as belonging to the requested room. It therefore compared Bob's room B request with Alice's room A booking and incorrectly detected a conflict. The time-overlap calculation itself was not the cause.

### Fix and verification

The lookup now filters by room ID:

```java
return bookings.stream()
        .filter(b -> b.room().id().equals(room.id()))
        .toList();
```

This matches the repository's existing waitlist lookup, which also identifies rooms by ID. The service still rejects overlapping bookings within a room, but unrelated rooms no longer interfere.

The original cross-room test now passes. `bookWaitlistsWhenSlotIsTaken` still verifies rejection of an overlapping request in the same room, and `backToBackBookingsAreConfirmed` verifies that touching endpoints remain allowed. The fix is recorded in commit `c9bdfd4`.

## 4. Milestone 2: implement `cancelBooking`

### Required behavior and implementation

Cancellation identifies a confirmed booking by its booking ID, not by the user's name. A user can have multiple bookings; cancelling one ID must not cancel the others.

The method implements the behavior specified in `TASK.md`:

1. Find the booking. If the ID is unknown, return without changing either collection.
2. Remember the booking's room, then remove that booking.
3. Read the remaining confirmed bookings and waitlist entries for that room.
4. Sort waitlist candidates by increasing `seq` to establish arrival order.
5. Skip any candidate whose requested interval overlaps any remaining booking.
6. Confirm the first eligible candidate, remove that candidate's waitlist entry, and return immediately.

The new confirmed booking retains the waiter's user, room, and requested interval, and receives a new booking ID. A waiter may request an interval extending beyond the cancelled booking's interval; eligibility depends on whether the entire requested interval is now free.

Sorting by `seq` prevents storage iteration order from determining priority. Checking all remaining bookings prevents promotion into a conflict elsewhere in the requested interval. Returning after the first promotion enforces the limit of one promotion per cancellation, even if several waiters could fit. If every candidate remains blocked, none is promoted.

Assuming the existing confirmed bookings satisfy the invariant, deleting one cannot introduce an overlap. Adding at most one replacement after checking it against every remaining same-room booking also preserves the invariant for this sequential service operation.

### Regression tests

Seven cancellation tests were added to `BookingServiceTest`:

| Test | What it verifies |
| --- | --- |
| `cancelBookingRemovesOnlyTheRequestedBooking` | The selected booking is removed and another booking remains. |
| `cancelUnknownBookingLeavesBookingsAndWaitlistUnchanged` | An unknown ID changes neither bookings nor waiters. |
| `cancelBookingPromotesWaitlistedUser` | A waiter becomes a confirmed booking with the expected user, room, and interval, and leaves the waitlist. |
| `cancelBookingPromotesOnlyLowestSeqWhenMultipleWaitersFit` | The smallest `seq` wins even after storage order is rearranged; only one waiter is promoted. |
| `cancelBookingSkipsWaiterWhoConflictsWithAnyRemainingBooking` | A blocked earlier waiter is skipped and a later eligible waiter is promoted; a conflict with a later-listed booking is not missed. |
| `cancelBookingPromotesNobodyWhenAllWaitersStillConflict` | Remaining bookings and the waitlist are preserved when no candidate fits. |
| `cancelBookingLeavesOtherRoomsBookingsAndWaitlistUnchanged` | Cancellation and promotion do not affect another room. |

The basic promotion test first confirms Alice for `[600, 660)` and waitlists Bob for `[630, 700)`. After Alice's booking is cancelled, its assertions check that exactly one confirmed booking exists, that it belongs to Bob in room A for `[630, 700)`, and that the room's waitlist is empty. These assertions demonstrate both sides of the transition, rather than checking deletion alone.

Implementation proceeded in three reviewed commits: basic removal and unknown-ID handling (`2c5e4c5`), promotion (`28ae6d2`), and additional edge-case tests (`dc1e69f`).

## 5. Milestone 3: detect and correct the availability defect

### Why the proposed query was wrong

The supplied patch checked whether an existing booking's start lay inside the requested interval:

```java
b.interval().start() >= interval.start()
        && b.interval().start() < interval.end()
```

That condition detects some overlaps but misses bookings that begin before the request and continue into it. Two regression cases exposed this omission:

| Existing booking | Requested interval | Shared time | Incorrect result | Expected result |
| --- | --- | --- | --- | --- |
| `[600, 660)` | `[630, 690)` | `[630, 660)` | Available | Unavailable |
| `[600, 720)` | `[630, 660)` | Entire request | Available | Unavailable |

In both cases, `600 >= 630` is false, so the original predicate fails to identify the conflict. The earlier tests passed because they did not call this newly introduced query. Passing them did not establish that `isAvailable` agreed with the booking rules.

This is an incorrect availability answer, not evidence that the query itself inserted overlapping bookings: `isAvailable` only reads state, while `book` independently checks overlap before confirming a booking.

### Correct overlap rule

The fix calls the existing domain method:

```java
if (b.interval().overlaps(interval)) {
    return false;
}
```

`TimeInterval.overlaps` already implements:

```java
return start < other.end && other.start < end;
```

For two nonempty half-open intervals `[a, b)` and `[c, d)`, they are disjoint exactly when `b <= c` or `d <= a`. Negating that statement gives `b > c` and `d > a`, equivalently `a < d && c < b`. Strict inequalities correctly exclude intervals that merely touch. Reusing this method keeps booking, promotion, and availability consistent without introducing another overlap formula.

### Tests and recovery

Six availability tests were added. Their recorded results before the fix and their final results are:

| Test | Original patch | Corrected code |
| --- | --- | --- |
| `isAvailableWhenRoomHasNoBookings` | Pass | Pass |
| `isAvailableIgnoresBookingsInOtherRooms` | Pass | Pass |
| `isAvailableRejectsOverlapWithLaterListedBooking` | Pass | Pass |
| `isAvailableRejectsOverlapWithBookingStartingEarlier` | Fail | Pass |
| `isAvailableRejectsRequestContainedInExistingBooking` | Fail | Pass |
| `isAvailableAllowsBackToBackIntervals` | Pass | Pass |

With the original patch, the expanded suite ran 23 tests and failed the two cases shown above, both with `expected: <false> but was: <true>`. The local transcript preserves that run. After replacing the predicate, all 23 tests passed. The corrected method and tests were committed as `95b8007` on `agent-attempt` and brought onto `main`.

**Workflow limitation:** the original flawed patch was not saved as its own commit, unlike the example sequence in the handout. Its evaluation and correction are documented in the local transcript; the Git history contains the corrected implementation and tests. No separate bad-patch commit is claimed here.

## 6. Final verification and commit history

The normal project test command is `mvn test`. For the verification recorded here, the installed JDK was selected explicitly and Maven used cached dependencies:

```sh
env JAVA_HOME=/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home \
    /opt/homebrew/bin/mvn -B -ntp -o test
```

The run completed on **August 28, 2026 at 00:50:20 EDT**:

| Suite | Tests | Failures | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: |
| `BookingServiceTest` | 18 | 0 | 0 | 0 |
| `TimeIntervalTest` | 5 | 0 | 0 | 0 |
| **Total** | **23** | **0** | **0** | **0** |

Maven reported `BUILD SUCCESS`. The total consists of the 10 original tests, seven cancellation tests, and six availability tests. This verifies the covered behaviors; it is not a claim of exhaustive testing, concurrent safety, or durable storage. The implementation remains an in-memory service with no added concurrency or persistence mechanisms.

The six pushed commits, in chronological Git order, are:

| Commit | Recorded change |
| --- | --- |
| `2c5e4c5` | Add basic booking cancellation and tests |
| `28ae6d2` | Promote an eligible waitlisted user after cancellation |
| `dc1e69f` | Test cancellation promotion edge cases |
| `c9bdfd4` | Fix booking lookup to filter by room ID |
| `3467ff8` | Document AI tool and model used for Lab 1 |
| `95b8007` | Add correct availability checks and regression tests |

The room-filter fix was made earlier in the working tree but committed after the cancellation series. Commit order should therefore not be interpreted as the exact order in which the changes were developed. At report preparation, the implementation branch was `main`, synchronized with `origin/main`.

## 7. AI supervision, transcript, and demonstration

The work used agent-generated changes with incremental review. The conversation records requests for explanations of assertions, booking IDs, waitlist ordering, the incorrect availability cases, and the overlap predicate, along with explicit approvals before commits. The README contains the tool/model disclosure. This report was also drafted with AI assistance and should be reviewed before use.

The local `transcripts/` directory contains `CODEX_TRANSCRIPT.md`, visible-event JSONL exports, and `EXPORT_NOTES.md`. The reusable Codex exporter captures saved user prompts, assistant replies, tool calls, and tool results through the last completed turn. It excludes internal instructions, private reasoning, and the current unfinished turn. It is a historical snapshot, not a live export; consult `EXPORT_NOTES.md` for the cutoff of the latest regenerated version.

The transcript files remain ignored by Git and were neither committed nor pushed. This follows the lab's explicit rule to keep transcripts out of the public fork and show them locally to course staff. This report summarizes the work; it does not replace the transcript.

For the TA demonstration:

1. Explain why a repository lookup caused the original service test to fail, then show the room-ID filter and passing tests.
2. Show the cancellation commit series and the promotion test; explain why the algorithm skips blocked waiters and stops after one promotion.
3. Show an availability counterexample, the two failing regression cases in the transcript, and the corrected overlap check.
4. Show the README disclosure, local transcript export, and current test result.

## 8. Conclusion and source material

The main lesson is that a passing suite is evidence only for the behaviors it exercises. The first defect required tracing a service failure into the repository. The cancellation task required verifying both confirmed bookings and waitlist state. The proposed availability query required new counterexamples despite passing the earlier tests. Together, these changes illustrate why reviewing assumptions and testing boundaries are necessary when supervising generated code.

Source material for this report:

- [Official Lab 1 handout](https://github.com/CMU-17-214/f2026/blob/main/labs/lab01.md).
- [Architecture at the tested revision](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/ARCHITECTURE.md) and [Milestone 2 specification](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/TASK.md).
- [Repository implementation](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/src/main/java/edu/cmu/cs214/booking/repo/InMemoryBookingStore.java), [service implementation](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/src/main/java/edu/cmu/cs214/booking/service/BookingService.java), and [time-interval rule](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/src/main/java/edu/cmu/cs214/booking/domain/TimeInterval.java).
- [Service tests](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/src/test/java/edu/cmu/cs214/booking/service/BookingServiceTest.java), [domain tests](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/src/test/java/edu/cmu/cs214/booking/domain/TimeIntervalTest.java), and the [original proposed patch](https://github.com/qfhu0ng/f26-lab01/blob/95b8007779ec5e232fac53d29aa62c471fc0c88e/changes/agent-attempt.patch).
- Local completed-session transcript for earlier failures and review history; the fresh Maven output reported in Section 6 for final verification.
