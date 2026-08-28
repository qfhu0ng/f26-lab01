package edu.cmu.cs214.booking.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;

import edu.cmu.cs214.booking.domain.Booking;
import edu.cmu.cs214.booking.domain.Room;
import edu.cmu.cs214.booking.domain.TimeInterval;
import edu.cmu.cs214.booking.domain.User;
import edu.cmu.cs214.booking.repo.InMemoryBookingStore;
import java.util.List;
import org.junit.jupiter.api.Test;

class BookingServiceTest {

    private final Room roomA = new Room("A", "Alpha", 10);
    private final Room roomB = new Room("B", "Beta", 4);
    private final User alice = new User("u1", "Alice");
    private final User bob = new User("u2", "Bob");

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
}
