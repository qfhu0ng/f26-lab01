package edu.cmu.cs214.booking.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

import edu.cmu.cs214.booking.domain.Booking;
import edu.cmu.cs214.booking.domain.Room;
import edu.cmu.cs214.booking.domain.TimeInterval;
import edu.cmu.cs214.booking.domain.User;
import edu.cmu.cs214.booking.domain.WaitlistEntry;
import edu.cmu.cs214.booking.repo.InMemoryBookingStore;
import java.util.List;
import org.junit.jupiter.api.Test;

class BookingServiceTest {

    private final Room roomA = new Room("A", "Alpha", 10);
    private final Room roomB = new Room("B", "Beta", 4);
    private final User alice = new User("u1", "Alice");
    private final User bob = new User("u2", "Bob");
    private final User charlie = new User("u3", "Charlie");

    private BookingService newService() {
        return new BookingService(new InMemoryBookingStore());
    }

    @Test
    void bookConfirmsWhenRoomIsFree() {
        BookingService svc = newService();
        BookingResult r = svc.book(roomA, alice, new TimeInterval(600, 660));
        assertInstanceOf(BookingResult.Confirmed.class, r);
    }

    @Test
    void bookWaitlistsWhenSlotIsTaken() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));
        BookingResult r = svc.book(roomA, bob, new TimeInterval(630, 700));
        assertInstanceOf(BookingResult.Waitlisted.class, r);
    }

    @Test
    void backToBackBookingsAreConfirmed() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));
        BookingResult r = svc.book(roomA, bob, new TimeInterval(660, 720));
        assertInstanceOf(BookingResult.Confirmed.class, r);
    }

    @Test
    void sameSlotInDifferentRoomsAreBothConfirmed() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));
        BookingResult r = svc.book(roomB, bob, new TimeInterval(600, 660));
        assertInstanceOf(BookingResult.Confirmed.class, r);
    }

    @Test
    void listBookingsReturnsConfirmedBookings() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));
        svc.book(roomA, bob, new TimeInterval(660, 720));
        assertEquals(2, svc.listBookings(roomA).size());
    }

    @Test
    void cancelBookingRemovesOnlyTheRequestedBooking() {
        BookingService svc = newService();
        BookingResult.Confirmed cancelled = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(600, 660)));
        BookingResult.Confirmed remaining = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, bob, new TimeInterval(660, 720)));

        svc.cancelBooking(cancelled.booking().id());

        assertEquals(List.of(remaining.booking()), svc.listBookings(roomA));
    }

    @Test
    void cancelUnknownBookingLeavesBookingsAndWaitlistUnchanged() {
        InMemoryBookingStore store = new InMemoryBookingStore();
        BookingService svc = new BookingService(store);
        BookingResult.Confirmed confirmed = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(600, 660)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, bob, new TimeInterval(600, 660)));
        var waitlistBefore = store.waitlistForRoom(roomA);

        svc.cancelBooking("missing");

        assertEquals(List.of(confirmed.booking()), store.allBookings());
        assertEquals(waitlistBefore, store.waitlistForRoom(roomA));
    }

    @Test
    void cancelBookingPromotesWaitlistedUser() {
        InMemoryBookingStore store = new InMemoryBookingStore();
        BookingService svc = new BookingService(store);
        BookingResult.Confirmed cancelled = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(600, 660)));
        TimeInterval requestedInterval = new TimeInterval(630, 700);
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, bob, requestedInterval));

        svc.cancelBooking(cancelled.booking().id());

        List<Booking> bookings = svc.listBookings(roomA);
        assertEquals(1, bookings.size());
        Booking promoted = bookings.get(0);
        assertEquals(bob, promoted.user());
        assertEquals(roomA, promoted.room());
        assertEquals(requestedInterval, promoted.interval());
        assertEquals(List.of(), store.waitlistForRoom(roomA));
    }

    @Test
    void cancelBookingPromotesOnlyLowestSeqWhenMultipleWaitersFit() {
        InMemoryBookingStore store = new InMemoryBookingStore();
        BookingService svc = new BookingService(store);
        BookingResult.Confirmed cancelled = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(600, 720)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, bob, new TimeInterval(600, 660)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, charlie, new TimeInterval(660, 720)));
        List<WaitlistEntry> waiters = store.waitlistForRoom(roomA);
        WaitlistEntry earliest = waiters.get(0);
        WaitlistEntry later = waiters.get(1);

        // The store interface does not promise iteration order; seq decides priority.
        store.removeWaitlistEntry(earliest.id());
        store.addWaitlistEntry(earliest);

        svc.cancelBooking(cancelled.booking().id());

        // Both intervals now fit, even together, but only the earliest may be promoted.
        List<Booking> bookings = svc.listBookings(roomA);
        assertEquals(1, bookings.size());
        assertEquals(bob, bookings.get(0).user());
        assertEquals(List.of(later), store.waitlistForRoom(roomA));
    }

    @Test
    void cancelBookingSkipsWaiterWhoConflictsWithAnyRemainingBooking() {
        InMemoryBookingStore store = new InMemoryBookingStore();
        BookingService svc = new BookingService(store);
        TimeInterval availableInterval = new TimeInterval(600, 660);
        BookingResult.Confirmed cancelled = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, availableInterval));
        BookingResult.Confirmed early = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(480, 540)));
        BookingResult.Confirmed late = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(660, 720)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, bob, new TimeInterval(630, 690)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, charlie, availableInterval));
        WaitlistEntry blocked = store.waitlistForRoom(roomA).get(0);

        svc.cancelBooking(cancelled.booking().id());

        // Bob conflicts with the later remaining booking, not the first one.
        List<Booking> bookings = svc.listBookings(roomA);
        assertEquals(3, bookings.size());
        assertTrue(bookings.contains(early.booking()));
        assertTrue(bookings.contains(late.booking()));
        assertTrue(bookings.stream().anyMatch(b -> b.user().equals(charlie)
                && b.interval().equals(availableInterval)));
        assertEquals(List.of(blocked), store.waitlistForRoom(roomA));
    }

    @Test
    void cancelBookingPromotesNobodyWhenAllWaitersStillConflict() {
        InMemoryBookingStore store = new InMemoryBookingStore();
        BookingService svc = new BookingService(store);
        BookingResult.Confirmed cancelled = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(600, 660)));
        BookingResult.Confirmed remaining = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, new TimeInterval(660, 720)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, bob, new TimeInterval(630, 690)));
        assertInstanceOf(BookingResult.Waitlisted.class,
                svc.book(roomA, charlie, new TimeInterval(650, 710)));
        var waitlistBefore = store.waitlistForRoom(roomA);

        svc.cancelBooking(cancelled.booking().id());

        assertEquals(List.of(remaining.booking()), svc.listBookings(roomA));
        assertEquals(waitlistBefore, store.waitlistForRoom(roomA));
    }

    @Test
    void cancelBookingLeavesOtherRoomsBookingsAndWaitlistUnchanged() {
        InMemoryBookingStore store = new InMemoryBookingStore();
        BookingService svc = new BookingService(store);
        TimeInterval interval = new TimeInterval(600, 660);
        BookingResult.Confirmed cancelled = assertInstanceOf(BookingResult.Confirmed.class,
                svc.book(roomA, alice, interval));
        assertInstanceOf(BookingResult.Confirmed.class, svc.book(roomB, bob, interval));
        // Room B's waiter arrives first, but must not be considered for room A.
        User dana = new User("u4", "Dana");
        assertInstanceOf(BookingResult.Waitlisted.class, svc.book(roomB, dana, interval));
        assertInstanceOf(BookingResult.Waitlisted.class, svc.book(roomA, charlie, interval));
        List<Booking> roomBBookingsBefore = svc.listBookings(roomB);
        var roomBWaitlistBefore = store.waitlistForRoom(roomB);

        svc.cancelBooking(cancelled.booking().id());

        assertEquals(List.of(charlie), svc.listBookings(roomA).stream().map(Booking::user).toList());
        assertEquals(List.of(), store.waitlistForRoom(roomA));
        assertEquals(roomBBookingsBefore, svc.listBookings(roomB));
        assertEquals(roomBWaitlistBefore, store.waitlistForRoom(roomB));
    }

    @Test
    void isAvailableWhenRoomHasNoBookings() {
        BookingService svc = newService();

        assertTrue(svc.isAvailable(roomA, new TimeInterval(600, 660)));
    }

    @Test
    void isAvailableIgnoresBookingsInOtherRooms() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));

        assertTrue(svc.isAvailable(roomB, new TimeInterval(600, 660)));
    }

    @Test
    void isAvailableRejectsOverlapWithLaterListedBooking() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(480, 540));
        svc.book(roomA, bob, new TimeInterval(600, 660));

        assertFalse(svc.isAvailable(roomA, new TimeInterval(570, 630)));
    }

    @Test
    void isAvailableRejectsOverlapWithBookingStartingEarlier() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));

        assertFalse(svc.isAvailable(roomA, new TimeInterval(630, 690)));
    }

    @Test
    void isAvailableRejectsRequestContainedInExistingBooking() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 720));

        assertFalse(svc.isAvailable(roomA, new TimeInterval(630, 660)));
    }

    @Test
    void isAvailableAllowsBackToBackIntervals() {
        BookingService svc = newService();
        svc.book(roomA, alice, new TimeInterval(600, 660));

        assertTrue(svc.isAvailable(roomA, new TimeInterval(540, 600)));
        assertTrue(svc.isAvailable(roomA, new TimeInterval(660, 720)));
    }
}
