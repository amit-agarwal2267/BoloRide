# BoloRide Business Policies

Status: Approved for Prototype v1
Version: 1.0
Target Prototype: 16 September 2026

## Purpose

This document defines deterministic business rules for BoloRide.

These rules must not be decided or overridden by the LLM.

The LLM may:
- understand user intent,
- extract information from conversation,
- ask clarification questions,
- explain decisions returned by backend services.

The LLM must not:
- calculate fares,
- determine offer eligibility,
- override vehicle capacity,
- decide whether a booking is valid,
- assign drivers,
- bypass confirmation requirements,
- blacklist callers,
- invent locations, prices, availability, or policies.

Backend services and deterministic policies remain the source of truth.

## Policy Index

1. Location Resolution Policy
2. Time Resolution Policy
3. Passenger Policy
4. Vehicle Eligibility Policy
5. Pricing Policy
6. Fare Presentation Policy
7. Quote Policy
8. Offer Eligibility Policy
9. Booking Policy
10. Confirmation Policy
11. Ride Lifecycle Policy
12. Driver Availability Policy
13. Dispatch Policy
14. Session Lifecycle Policy
15. Security Guardrail Policy
16. Human Review / Blacklist Policy

## 1. Location Resolution Policy

### Purpose

Resolve pickup and destination locations with sufficient geographic
confidence before they are used for pricing or booking.

### Inputs

- Raw location text from the caller
- Existing conversation context
- Saved places, if available
- Previously resolved pickup location
- Maps provider candidates
- City
- State
- Country

### Rules

1. A location must not be treated as resolved only because the LLM
   understood the text.

2. If a pickup address does not contain enough geographic information
   to resolve it confidently, request the missing context.

3. If city information is missing and is required for resolution,
   ask the caller for the city.

4. Do not automatically ask for state after every city.

5. Ask for state only when the city produces multiple genuinely
   plausible geographic candidates and state information is required
   to distinguish them.

6. Never assume a particular state merely because one city is more
   commonly associated with that state.

7. A resolved pickup may provide geographic context for an ambiguous
   destination query.

8. Example:
   Pickup is resolved to Kota, Rajasthan.
   Destination supplied as "station".
   Destination search should use Kota, Rajasthan as geographic context.

9. An ambiguous destination such as "station" must not automatically
   become "Kota Junction" based purely on LLM knowledge.

10. Maps/provider results must provide candidate locations.

11. If multiple plausible destination candidates remain, ask the user
    to clarify.

12. An explicitly provided destination city overrides geographic
    context inferred from the pickup.

13. If no suitable location candidate is found, ask the user for a more
    specific location instead of fabricating one.

14. Previously resolved locations must be replaceable when the caller
    corrects them.

### Output / Decision

A location can result in one of these conceptual states:

- unresolved
- needs_clarification
- search_required
- candidate_selection_required
- resolved

### Failure / Edge Cases

- Missing city
- Ambiguous city across states
- Multiple railway stations
- Maps provider returns no result
- User corrects a previously resolved location
- Source and destination are both ambiguous
- Explicit destination geography differs from source city

### LLM Responsibilities

The LLM may:

- extract location text,
- understand that the caller is providing pickup or destination,
- ask the clarification requested by the location workflow,
- explain candidate options naturally.

### LLM Must Not

The LLM must not:

- invent coordinates,
- invent provider place IDs,
- declare an ambiguous location resolved,
- select a maps candidate without required policy validation,
- fabricate a station or landmark.

### Hard Invariants

- Booking must never use an unresolved pickup.
- Booking must never use an unresolved destination.
- A maps failure must never become a fabricated location.
- Explicit user corrections replace stale location state.

### Additional Prototype Rules

15. Ola Maps is the default location provider for prototype v1.

16. Google Maps may be used as the secondary/fallback provider.

17. Location confidence must come from provider-backed geographic
    resolution rather than LLM confidence alone.

18. A pickup does not require exact house-number resolution before it
    can become usable for booking.

19. A location may be considered sufficiently resolved when the system
    has a provider-backed match containing enough geographic information
    to navigate to the pickup area, including at minimum:

    - society/locality or equivalent identifiable area,
    - city,
    - state,
    - valid provider-backed coordinates.

20. A nearby provider-backed landmark may be used as the navigable
    pickup reference when an exact house/building number cannot be
    resolved.

21. The caller's original address text must still be retained so the
    driver can use it together with the resolved navigable location.

22. House/building-level final discovery may be completed by the driver
    after reaching the resolved pickup area.

23. This relaxed house-number rule must not allow the system to accept
    an ambiguous city, locality, or unrelated landmark.

24. When multiple plausible candidates remain, the caller must clarify
    rather than the system selecting one arbitrarily.

25. For voice interaction, the agent should normally present at most
    3 candidate locations at one time.

26. If more than 3 candidates exist, backend ranking should select the
    3 strongest candidates for clarification rather than reading a long
    list over voice.

27. Contextual destination search radius is configuration-driven.

28. Prototype defaults are:

    - dense/urban operating area: approximately 1 km
    - sparse/rural operating area: approximately 20 km

29. Example urban operating areas include Kota, Jaipur, and Indore.

30. Example sparse/rural operating areas include Weir, Hindoli, and
    Gangapur.

31. The area classification and search radius must be backend
    configuration, not an LLM decision.

32. If no suitable candidate is found inside the initial contextual
    radius, the system should request additional location information
    rather than silently selecting a distant candidate.

### Prototype Decisions

- Default provider: Ola Maps
- Secondary/fallback provider: Google Maps
- Maximum candidates normally spoken per clarification turn: 3
- Dense/urban contextual radius: approximately 1 km
- Sparse/rural contextual radius: approximately 20 km
- Exact house-number resolution is not mandatory when a sufficiently
  precise provider-backed locality/society/landmark and coordinates
  have been resolved.

## 2. Time Resolution Policy

### Purpose

Convert conversational ride-time expressions into an unambiguous,
timezone-aware timestamp and validate whether that timestamp is allowed
for booking.

Natural-language understanding may involve the LLM, but timestamp
construction, timezone conversion, comparison, and validation must be
performed deterministically by backend Python code.

### Inputs

- Raw time expression
- Structured temporal information extracted from the conversation
- Current backend date and time
- Existing requested ride time
- Configured conversational timezone
- Maximum advance-booking window

### Prototype Configuration

- Conversational timezone: Asia/Kolkata
- Maximum advance-booking window: 7 days
- Persistent absolute timestamps: UTC

### Rules

1. The prototype conversational timezone is Asia/Kolkata.

2. Absolute ride timestamps must be persisted in UTC.

3. Conversion between Asia/Kolkata and UTC must be performed
   deterministically using Python datetime/timezone functionality.

4. The LLM must not be used merely to perform timezone conversion,
   timestamp arithmetic, or timestamp comparison.

5. The LLM may interpret natural-language temporal expressions such as:

   - "kal subah 6:30"
   - "parso"
   - "aaj shaam"
   - "saade chhe"
   - "tomorrow morning"

6. The LLM should return structured temporal meaning rather than being
   treated as the authority for the final timestamp.

7. Backend Python logic must construct and validate the final
   timezone-aware timestamp from the structured temporal information.

8. Relative dates must be resolved against the actual current date in
   Asia/Kolkata.

9. The backend system clock is authoritative for determining the
   current time.

10. A requested scheduled time that has already passed must not silently
    roll forward to another day.

11. If the resulting timestamp is in the past, the request is invalid
    and the caller must be asked for another time.

12. AM/PM must not be guessed when the caller's expression and
    conversation context do not provide sufficient information.

13. Daypart expressions may disambiguate time.

    Example:

    "kal subah 6:30"

    provides sufficient context to resolve 6:30 as a morning time.

14. A statement such as:

    "kal 6:30"

    may require clarification when AM/PM cannot otherwise be determined
    reliably.

15. Immediate expressions include examples such as:

    - "abhi"
    - "right now"
    - "as soon as possible"

16. Immediate-ride intent must still produce an actual timestamp.

17. For an immediate ride, the backend must record the current
    timezone-aware timestamp representing when the immediate booking
    request is being made.

18. The immediate timestamp must be generated from the backend system
    clock rather than generated or guessed by the LLM.

19. The maximum advance-booking window for prototype v1 is 7 days.

20. A scheduled ride may not be requested for a timestamp more than
    7 days ahead of the current time.

21. Advance-window validation must be performed using backend Python
    logic.

22. If the requested time exceeds the 7-day window, the request must be
    rejected and the caller informed that BoloRide currently supports
    bookings only up to 7 days in advance.

23. If the caller changes the requested ride time, the latest valid
    value replaces the previous value.

24. A material requested-time change invalidates previous booking
    confirmation.

25. A requested-time change must invalidate or revalidate any quote
    whose pricing depends on ride time.

26. Offer eligibility must also be revalidated when eligibility depends
    on requested time.

27. Changing between an immediate ride and a scheduled ride is a
    material time change.

28. Conversation crossing midnight must not cause relative dates to be
    interpreted using stale session-start dates. Resolution must use
    the appropriate current backend date when the expression is
    processed.

### Output / Decision

A time request may result in:

- immediate
- resolved
- needs_clarification
- past_time
- beyond_advance_booking_window
- invalid

A valid result must contain an unambiguous timezone-aware timestamp.

For persistence, that timestamp must be converted to UTC.

For immediate rides, the result must also retain that the request was
immediate where this distinction is useful to application behavior.

### Failure / Edge Cases

- "kal 6:30" without sufficient AM/PM context
- "aaj 6 baje" when that time has already passed
- "parso subah" without a sufficiently precise booking time
- Caller changes 7:00 to 6:30
- Caller changes scheduled ride to "abhi"
- Caller changes immediate ride to scheduled ride
- Requested timestamp is more than 7 days away
- Conversation crosses midnight
- LLM extracts an impossible date/time
- LLM-produced structured time conflicts with deterministic validation

### LLM Responsibilities

The LLM may:

- understand Hindi, Hinglish, and English temporal expressions,
- extract structured temporal meaning,
- identify missing temporal information,
- ask natural clarification questions,
- communicate deterministic validation failures naturally.

### LLM Must Not

The LLM must not:

- act as the authoritative system clock,
- calculate UTC conversion,
- perform authoritative timestamp arithmetic,
- determine whether the final timestamp is in the past,
- determine whether the timestamp exceeds the 7-day limit,
- silently roll a past time into another day,
- invent AM/PM when materially ambiguous,
- preserve confirmation after a material time change.

### Backend Responsibilities

Backend Python logic must:

- obtain the authoritative current timestamp,
- resolve structured relative date information against the current date,
- construct timezone-aware timestamps,
- perform Asia/Kolkata to UTC conversion,
- compare timestamps,
- enforce the 7-day advance-booking limit,
- reject past timestamps,
- record the timestamp for immediate bookings.

### Hard Invariants

- Every bookable ride has an unambiguous timestamp.
- Immediate rides still record an actual timestamp.
- Scheduled timestamps cannot be in the past.
- Scheduled timestamps cannot exceed the 7-day advance-booking window.
- UTC conversion and timestamp validation are deterministic backend
  operations.
- The LLM is never the authority for current time or timestamp
  arithmetic.
- Material time changes invalidate existing confirmation.
- Time-sensitive quotes must be revalidated after a material time
  change.

### Open Decisions

None required for prototype v1.

## 3. Passenger Policy

### Purpose

Determine the passenger count used for vehicle eligibility while
avoiding unnecessary conversational questions.

The system should support normal single-passenger bookings without
forcing an additional question while still correctly handling larger
groups.

### Inputs

- Explicit passenger count from caller, if provided
- Existing passenger count in ride context
- Configured default passenger count
- Passenger-count source

### Prototype Configuration

- Default passenger count: 1
- Passenger-count source:
  - DEFAULT
  - USER_PROVIDED
- Special infant/child capacity handling: not supported in prototype v1
- Luggage-capacity matching: not supported in prototype v1

### Rules

1. Passenger count must have a valid positive whole-number value before
   vehicle-capacity eligibility is finalized.

2. When the caller does not provide a passenger count, prototype v1
   uses a default passenger count of 1.

3. A defaulted passenger count must be distinguishable from a value
   explicitly provided by the caller.

4. Passenger-count source must therefore distinguish at minimum:

   - DEFAULT
   - USER_PROVIDED

5. The agent should not automatically ask every caller for passenger
   count when the default value is sufficient.

6. If the caller explicitly provides a passenger count, that value
   replaces the default.

7. If the caller later corrects passenger count, the latest valid
   explicit value replaces the previous value.

8. Passenger count must be a positive whole number.

9. Zero passenger count is invalid.

10. Negative passenger count is invalid.

11. Fractional passenger count is invalid.

12. Invalid or unclear passenger counts require clarification rather
    than silently substituting the default.

13. Vehicle eligibility must be evaluated using the current passenger
    count.

14. Vehicle eligibility must be recalculated whenever passenger count
    changes.

15. If the new passenger count exceeds the capacity of the currently
    selected vehicle, that vehicle selection becomes invalid.

16. When vehicle selection becomes invalid, a vehicle-specific selected
    quote must also be invalidated.

17. The caller must then select from currently eligible vehicle options.

18. Passenger-count changes that materially affect the selected ride
    product invalidate previous booking confirmation.

19. For prototype v1, every passenger counts toward the configured seat
    capacity of the vehicle.

20. Prototype v1 does not implement different capacity calculations for
    infants or children.

21. Prototype v1 does not perform deterministic luggage-capacity
    matching.

22. The LLM must not claim that a particular amount of luggage will fit
    unless future structured vehicle-capacity data explicitly supports
    that determination.

23. A caller mentioning substantial luggage may be informed that
    luggage-specific capacity matching is not supported and may choose
    a larger eligible vehicle where available.

### Output / Decision

Passenger state may be:

- valid_default
- valid_user_provided
- needs_clarification
- invalid
- vehicle_reselection_required

A valid passenger state contains:

- passenger_count
- passenger_count_source

### Failure / Edge Cases

- Caller provides no passenger count
- "Main akela hoon"
- "Hum 5 log hain"
- Caller changes 2 passengers to 5
- Caller requests a 4-seat vehicle for 5 passengers
- Caller says zero passengers
- Caller provides a negative value
- Caller provides an unclear quantity
- Caller mentions substantial luggage
- Passenger correction makes selected vehicle ineligible
- Passenger correction occurs after booking confirmation

### LLM Responsibilities

The LLM may:

- extract explicit passenger counts,
- understand natural-language quantities,
- understand passenger-count corrections,
- ask clarification when the quantity cannot be reliably extracted,
- explain that a selected vehicle is no longer eligible,
- communicate eligible vehicle options returned by backend services.

### LLM Must Not

The LLM must not:

- override configured vehicle capacity,
- reduce passenger count to make a vehicle eligible,
- silently replace an invalid explicit passenger count with the default,
- claim luggage compatibility without supporting structured data,
- preserve an incompatible vehicle selection after passenger count
  increases,
- preserve confirmation after a material eligibility change.

### Backend Responsibilities

Backend policy/service logic must:

- apply the default passenger count of 1 when appropriate,
- record whether the value was defaulted or user-provided,
- validate positive whole-number passenger counts,
- evaluate vehicle capacity,
- invalidate incompatible vehicle selections,
- invalidate affected quotes,
- invalidate confirmation where required.

### Hard Invariants

- passenger_count >= 1.
- Passenger count must be a whole number.
- Explicit valid caller-provided passenger count overrides the default.
- Invalid explicit input must not silently fall back to 1.
- Vehicle seat capacity must be greater than or equal to passenger count.
- Passenger-count changes trigger vehicle eligibility re-evaluation.
- An ineligible selected vehicle cannot proceed to booking.
- A materially affected quote cannot remain selected as though nothing
  changed.

### Open Decisions

None required for prototype v1.

## 4. Vehicle Eligibility Policy

### Purpose

Determine which configured vehicle categories can serve a ride.

### Inputs

- Passenger count
- Vehicle type
- Seat capacity
- Vehicle active status
- Requested ride type
- Vehicle availability

### Rules

1. Vehicle types are data/configuration and must not be hardcoded into
   conversational logic.

2. New vehicle categories may be introduced without changing the
   fundamental booking workflow.

3. Every vehicle type must define a passenger seat capacity.

4. A vehicle type is eligible only when:

   seat_capacity >= passenger_count

5. Inactive vehicle types must never be offered.

6. Only currently available vehicle categories should be offered.

7. Vehicle display names must come from configured vehicle data.

8. Examples of possible configured categories include:

   - Bike: 1 passenger
   - Auto: 3 passengers
   - AC Cab: 4 passengers
   - Non-AC Cab: 4 passengers
   - Premium Cab: configured capacity
   - XL Cab: 6 passengers

   These examples must not become hardcoded eligibility logic.

### Output / Decision

- eligible vehicle options
- unavailable vehicle options
- reason for ineligibility where useful

### Failure / Edge Cases

- passenger count exceeds all configured capacities
- no vehicles available
- requested vehicle inactive
- passenger count missing where capacity validation is required

### LLM Responsibilities

The LLM may:

- understand passenger-count statements,
- understand vehicle preferences,
- explain available options.

### LLM Must Not

The LLM must not:

- override seat capacity,
- invent vehicle categories,
- invent vehicle availability,
- offer an ineligible vehicle.

### Hard Invariants

- seat_capacity must be greater than or equal to passenger_count.
- inactive vehicles cannot be booked.
- unavailable vehicles cannot be booked.

### Prototype Decisions

- Passenger count does not need to be explicitly collected for every
  ride. The configured default is 1.
- Every passenger counts toward vehicle seat capacity in prototype v1.
- Special infant/child capacity rules are outside prototype v1.
- Luggage-capacity matching is outside prototype v1.

## 5. Pricing Policy

### Purpose

Calculate estimated ride prices deterministically.

### Inputs

- Vehicle type
- Pricing rules
- Route distance
- Estimated duration where applicable
- Requested time
- Toll estimate
- Pickup/destination access charges
- Parking charges
- Applicable offers
- Applicable taxes

### Rules

1. The LLM must never calculate fare.

2. Vehicle pricing must be configurable.

3. Pricing may include:

   - base fare
   - per-kilometre charge
   - per-minute charge
   - minimum fare
   - night surcharge
   - toll
   - parking/access charge
   - offer discount
   - taxes

4. Night charges must follow configured rules and effective times.

5. Toll charges depend on route information rather than being assumed
   solely from vehicle type.

6. Parking/access charges may depend on pickup or destination location,
   such as airports.

7. Monetary calculations must use fixed-precision decimal arithmetic.

8. Fare calculations must retain individual components even when those
   components are not initially spoken to the caller.

### Output / Decision

A structured quote containing:

- estimated total
- currency
- applicable fare components
- applied pricing rules
- applicable discount
- applicable tax
- quote validity information

### Hard Invariants

- The LLM cannot alter calculated prices.
- Quote total must be derived from recorded pricing components.
- Applied charges must correspond to active pricing rules.

## 6. Fare Presentation Policy

### Purpose

Control how fare information is communicated to callers.

### Rules

1. Default response should present the estimated total fare first.

2. Do not automatically read the complete fare breakdown.

3. If night charges are included, inform the caller that applicable
   night charges are included.

4. If toll is included, inform the caller that estimated toll charges
   are included.

5. If parking/access charges are included, mention that applicable
   parking/access charges are included.

6. Detailed component amounts should be provided when the caller asks.

7. Distinguish between:

   - policy explanation:
     "When do night charges apply?"

   - quote explanation:
     "How much night charge is included in my fare?"

8. Policy explanations come from pricing rules.

9. Quote-specific amounts come from the stored quote components.

10. Estimated values must be described as estimates rather than
    guaranteed final charges.

## 7. Quote Policy

### Purpose

Define when a fare quote is valid, when it can be presented or selected,
and when it must be recalculated before booking.

A quote represents an estimated price for a specific ride configuration
at a particular point in time.

### Inputs

- Quote ID
- User ID / session context
- Resolved pickup
- Resolved destination
- Requested time
- Passenger count
- Vehicle type
- Pricing result
- Applied offer, if any
- Quote creation time
- Quote expiry time
- Current ride context

### Rules

1. A quote must be generated by the pricing service.

2. The LLM must never construct, modify, or recalculate a quote.

3. Every quote must be associated with the ride inputs used to calculate it.

4. A quote must have a unique identifier.

5. A quote must record when it was created.

6. A quote must have a configurable validity period.

7. An expired quote cannot be used directly for booking.

8. If an expired quote is selected for booking, the system must obtain
   a new quote before asking for final booking confirmation.

9. A material change to the ride context invalidates the selected quote.

10. Material changes include at minimum:

    - pickup change
    - destination change
    - requested-time change where pricing depends on time
    - passenger-count change that changes vehicle eligibility
    - vehicle-type change
    - applied-offer change

11. When a quote becomes invalid, any confirmation associated with that
    quote must also become invalid.

12. A caller may request fare estimates without intending to book.

13. Generating or selecting a quote must not itself create a booking.

14. A caller may compare multiple vehicle quotes before choosing one.

15. Only the quote for the currently selected vehicle may be used for
    final booking.

16. The final booking flow must use the latest valid quote associated
    with the current ride context.

17. Quote amounts must remain immutable after creation.

18. If pricing changes, a new quote must be created rather than modifying
    the previous quote.

19. Quote persistence follows the Prototype Quote Lifetime rules below.
    Unconfirmed quotes are ephemeral. The quote associated with a
    successfully created booking becomes durable booking history.

### Output / Decision

A quote can conceptually be:

- valid
- expired
- invalidated_by_context_change
- superseded

The policy determines whether the quote:

- may be presented,
- may be selected,
- requires recalculation,
- may proceed toward confirmation.

### Failure / Edge Cases

- Quote expires while caller is deciding
- Caller changes vehicle after hearing price
- Caller changes pickup or destination
- Caller changes journey time
- Offer becomes unavailable
- Pricing service fails during requote
- Multiple vehicle quotes exist simultaneously
- Caller refers to an older quoted price

### LLM Responsibilities

The LLM may:

- ask which quoted vehicle the caller prefers,
- explain that an estimate has changed,
- tell the caller that a fresh estimate is required,
- present quote information returned by services.

### LLM Must Not

The LLM must not:

- extend quote validity,
- modify quote amount,
- reuse an invalid quote,
- promise that an estimate is a guaranteed final fare,
- choose a quote without sufficient user intent,
- treat quote selection as booking confirmation.

### Hard Invariants

- An expired quote cannot be used for final booking.
- An invalidated quote cannot be used for final booking.
- Quote selection is not booking confirmation.
- Material ride changes invalidate the relevant selected quote.
- Quote amounts are immutable.
- Final booking must reference a valid quote for the current ride context.

### Prototype Quote Lifetime

20. A quote is valid for a maximum of 20 minutes from generation.

21. An unconfirmed quote is also invalidated when its voice session/call
    ends.

22. Therefore an unconfirmed quote expires at whichever occurs first:

    - 20 minutes after quote generation, or
    - termination of the current call/session.

23. Quotes generated during browsing, fare comparison, or abandoned
    booking flows are ephemeral and do not need permanent business
    persistence.

24. When the caller explicitly confirms a booking and that booking is
    successfully created, the quote associated with that booking becomes
    part of the durable booking record/history.

25. A confirmed booking quote must remain retained even if the ride is
    later cancelled.

26. Cancellation must not delete or overwrite the historical quote.

27. Customer final payable ride cost and historical quoted amount are
    separate concepts.

28. For prototype v1, when a ride is successfully cancelled before the
    trip begins, the customer's final ride cost becomes zero.

29. The historical booking quote remains available internally for audit,
    debugging, analytics, and support.

30. When an expired quote is refreshed, the new quote must be compared
    with the previous quote before booking continues.

31. If the refreshed fare differs from the previous fare, the caller
    must be informed of the new estimated total.

32. Any fare change requires new explicit booking confirmation.

33. The previous confirmation must not authorize booking against the
    changed fare.

34. The old quote must remain immutable; the refreshed calculation
    produces a new quote.

### Caller Experience After Quote Expiry

A natural response may be equivalent to:

"Main ek baar phir se aapka fare check kar leta hoon. Aapka previous
quote expire ho gaya hai. Naya estimated fare ₹X hai. Kya aap is fare
par ride book karna chahenge?"

The exact wording may vary naturally according to conversation language.

The fare value must always come from the new backend-generated quote.

### Prototype Decisions

- Quote validity: 20 minutes
- Unconfirmed quote lifetime: current call/session or 20 minutes,
  whichever ends first
- Unconfirmed quotes: ephemeral
- Successfully booked quote: durable
- Booked quote remains retained after cancellation
- Successful pre-trip cancellation: customer final ride cost = 0
- Any refreshed fare change requires the new fare to be communicated
  and explicitly reconfirmed

## 8. Offer Eligibility Policy

### Purpose

Determine whether a configured promotional offer may be applied to a
specific user and ride.

### Inputs

- User
- Offer
- Current time
- Ride context
- Previous completed ride count
- Previous offer usage
- Vehicle type
- Estimated fare before discount
- Pickup/destination geography where applicable

### Rules

1. Offer definitions must be configuration/data driven.

2. The LLM must never determine offer eligibility.

3. An offer must be active to be eligible.

4. The current time must fall within the offer's configured validity
   period when a validity period exists.

5. Eligibility rules may include:

   - new-customer-only
   - existing-customer-only
   - minimum previous ride count
   - minimum fare
   - percentage discount
   - fixed discount
   - maximum discount
   - per-user usage limit
   - overall redemption limit
   - eligible vehicle types
   - eligible geographic areas

6. Only rules actually configured for an offer should be evaluated.

7. An offer must satisfy all of its required eligibility conditions.

8. Percentage discounts must respect a configured maximum discount
   where one exists.

9. Offer usage must not exceed the configured per-user limit.

10. Offer usage must not exceed the configured overall redemption limit.

11. An offer that was eligible earlier in the conversation must be
    revalidated before it affects the final booking quote.

12. A material ride-context change may require offer eligibility to be
    evaluated again.

13. Applying an offer must result in pricing producing a new quote.

14. The original quote must not be mutated to insert the discount.

15. For the prototype, only one promotional offer may be applied to a
    quote unless stacking is explicitly introduced later.

### Output / Decision

- eligible
- ineligible
- eligibility reason
- calculated discount constraints for the pricing service

### Failure / Edge Cases

- Offer expires during conversation
- Usage limit reached
- Minimum fare no longer satisfied after ride change
- Vehicle changes to an ineligible category
- New-user offer requested by existing customer
- Offer becomes inactive
- Redemption race between concurrent bookings

### LLM Responsibilities

The LLM may:

- understand that the caller is asking about offers,
- request available offers through the appropriate tool,
- explain eligibility results returned by services,
- ask whether the caller wants to apply an eligible offer.

### LLM Must Not

The LLM must not:

- declare an offer eligible,
- invent an offer,
- change discount values,
- bypass usage limits,
- combine offers unless explicitly permitted,
- promise a discount before eligibility validation.

### Hard Invariants

- Ineligible offers cannot affect pricing.
- Expired or inactive offers cannot be applied.
- Usage limits cannot be bypassed by the LLM.
- Applying/removing an offer requires a new quote.
- Offer eligibility must be revalidated before final booking.

### Prototype Offer Discovery Rules

16. Callers do not verbally enter promotional codes in prototype v1.

17. Promo-code dictation is intentionally unsupported because voice
    recognition of arbitrary codes can introduce unnecessary errors and
    conversational friction.

18. Offers are discovered from active offer data maintained by BoloRide.

19. New-customer onboarding offers may be suggested automatically.

20. For prototype v1, a customer remains eligible for automatic
    new-customer offer discovery until they have completed 3 rides,
    subject to the individual offer's configured eligibility rules.

21. Ride count for this rule is based on COMPLETED rides.

22. CANCELLED rides do not count toward the first 3 completed rides.

23. Automatic suggestion does not mean automatic application.

24. The caller must still accept an offered promotion before it is
    applied to the ride quote.

25. A caller may explicitly ask whether any offers are currently
    available.

26. In that case, the backend checks currently active general-public
    offers and returns eligible options.

27. The LLM must not search its own knowledge for promotional offers.

28. Only offers present and active in BoloRide's offer data may be
    presented.

29. Prototype v1 does not reserve an offer merely because it was shown
    to the caller.

30. Offer eligibility must be revalidated when producing the final
    booking quote.

31. Only one promotional offer may affect a quote in prototype v1.

### Prototype Decisions

- Spoken promo-code entry: unsupported
- New-customer offers: proactively discover/suggest during first
  3 completed rides
- General-public offers: discover on caller request
- Automatic suggestion does not automatically apply an offer
- CANCELLED rides do not count toward completed-ride eligibility
- Offer reservation: not required for prototype v1
- Final eligibility is revalidated when generating the booking quote

## 9. Booking Policy

### Purpose

Determine whether the current ride context contains everything required
to attempt creation of a ride booking.

### Inputs

- User
- Resolved pickup
- Resolved destination
- Requested time
- Passenger count
- Selected vehicle type
- Selected quote
- Applied offer, if any
- Explicit confirmation state
- Idempotency information
- Existing booking state

### Rules

1. Booking is a distinct operation from:

   - fare estimation
   - checking vehicles
   - checking offers
   - selecting a vehicle
   - selecting a quote

2. Before booking may be attempted, the system must have:

   - customer identity established according to the Customer Identification
     and Returning Caller Verification rules applicable to the operation,
   - resolved pickup,
   - resolved destination,
   - valid requested time,
   - valid passenger count where required,
   - selected eligible vehicle type,
   - valid current quote,
   - explicit booking confirmation.

3. Missing required information must be collected before booking.

4. The system must not infer confirmation merely because all booking
   information has been collected.

5. Booking creation must be idempotent.

6. A retry caused by timeout or transport failure must not create a
   duplicate ride.

7. Repeated user confirmation for the same already-created booking must
   not create another booking.

8. Provider booking failures must not be represented to the caller as
   successful bookings.

9. A provider timeout with uncertain outcome must be reconciled before
   blindly attempting another booking.

10. The booking record must retain ride snapshots rather than depending
    on mutable saved-place data.

11. Successful booking should produce sufficient information to identify
    and communicate the ride to the caller.

12. Driver dispatch is downstream of booking eligibility and must not be
    decided by the LLM.

### Output / Decision

The booking request may result in:

- missing_information
- confirmation_required
- invalid_quote
- booking_in_progress
- booked
- failed
- outcome_unknown

### Failure / Edge Cases

- Missing destination
- Invalid requested time
- Selected vehicle becomes unavailable
- Quote expires
- Offer becomes invalid
- User confirms twice
- Provider times out
- Provider rejects booking
- Internal persistence succeeds but provider response is lost
- User changes ride details immediately before confirmation

### LLM Responsibilities

The LLM may:

- collect missing information,
- present the booking summary,
- request explicit confirmation,
- communicate booking results returned by the service.

### LLM Must Not

The LLM must not:

- directly create provider bookings,
- bypass required information,
- treat vehicle selection as confirmation,
- treat fare acceptance as confirmation,
- invent a successful booking,
- retry an uncertain booking without service-level idempotency handling.

### Hard Invariants

- No booking without resolved pickup.
- No booking without resolved destination.
- No booking using an invalid requested time.
- No booking with an ineligible vehicle.
- No booking using an expired or invalidated quote.
- No booking without explicit confirmation.
- One logical booking request must not create multiple rides.

### Customer Identification and Returning Caller Verification

#### Purpose

Identify the customer associated with an incoming phone call and provide
sufficient prototype-level verification before accessing or modifying
their ride data.

#### Customer Profile

A customer profile contains at minimum:

- phone number
- name
- age
- creation timestamp

Age is collected only during first-time onboarding.

Returning callers are not required to provide age again during normal
ride operations.

#### First-Time Caller Onboarding

1. The incoming caller phone number should be obtained automatically from
   the telephony/call metadata where available.

2. Phone numbers must be normalized before storage and comparison.

3. If no customer exists for the detected phone number, the caller is
   treated as a first-time customer.

4. First-time onboarding must collect at minimum:

   - name
   - age

5. The detected phone number is associated with the newly created
   customer profile.

6. The caller should not normally be asked to manually dictate their
   phone number when it has already been reliably obtained from call
   metadata.

#### Returning Caller Identification

7. When an incoming phone number matches an existing customer, the
   system identifies the corresponding customer record.

8. Before exposing or modifying persisted ride information, the caller's
   name must also match the name stored for that customer.

9. Prototype v1 therefore uses the combination of:

   - automatically detected phone number
   - caller-provided/confirmed name

   as sufficient returning-caller verification.

10. Age is not required again for routine returning-caller verification.

11. A phone-number match alone must not be treated as sufficient when the
    requested operation modifies an existing ride.

12. A name match without the detected phone-number match is also not
    sufficient.

13. Both phone and name must correspond to the same stored customer
    record.

#### Name Matching

14. Name comparison should tolerate reasonable normalization such as:

    - capitalization differences
    - leading/trailing whitespace
    - repeated whitespace

15. The system must not silently accept a substantially different name.

16. If the name cannot be matched confidently, the caller should be
    asked to repeat or clarify their name.

17. The LLM may help understand the spoken name, but customer matching
    must be performed by backend logic against persisted customer data.

#### Returning Ride Operations

18. After successful customer verification, persisted rides belonging to
    that customer may be queried for supported operations such as:

    - ride status
    - cancellation
    - future modification operations where supported

19. Only rides belonging to the verified customer may be returned.

20. The LLM must not query or expose another customer's rides.

#### Cancellation

21. A returning cancellation request follows:

    incoming phone
        -> customer lookup
        -> name verification
        -> cancellable ride lookup
        -> target ride resolution
        -> explicit cancellation confirmation
        -> cancellation

22. If no cancellable ride exists for the verified customer, the system
    must communicate that result without exposing unrelated ride data.

23. If exactly one cancellable ride exists, it may be presented for
    cancellation confirmation.

24. If multiple cancellable rides exist, the caller must identify which
    ride should be cancelled.

#### Failure / Edge Cases

- Incoming phone number does not exist
- Name does not match the phone-number customer
- Speech recognition produces an uncertain name
- Multiple active rides exist
- Caller asks about another person's ride
- Phone metadata is unavailable
- Duplicate customer data exists unexpectedly

#### LLM Responsibilities

The LLM may:

- collect the caller's name,
- understand spelling/correction of a spoken name,
- communicate verification failures naturally,
- ask which ride the caller means when multiple rides are returned.

#### LLM Must Not

The LLM must not:

- choose a customer based only on conversational similarity,
- override a phone-number mismatch,
- expose another customer's rides,
- treat age as required on every returning call,
- cancel a ride before customer and ride resolution are complete.

#### Backend Responsibilities

Backend services must:

- normalize detected phone numbers,
- lookup the customer by phone number,
- compare the provided name with persisted customer data,
- enforce customer ownership of queried rides,
- return only rides belonging to the verified customer.

#### Hard Invariants

- First-time onboarding collects name and age.
- Returning verification requires detected phone number + matching name.
- Age is not repeatedly requested for normal returning calls.
- Ride ownership is enforced by backend services.
- Another customer's ride must never be exposed or modified.

## 10. Confirmation Policy

### Purpose

Ensure that a ride is created only after the caller explicitly confirms
the current booking details.

### Inputs

- Current ride context
- Selected vehicle
- Current quote
- Booking summary
- User response
- Confirmation state
- Context version / material changes

### Rules

1. Explicit confirmation is required before booking.

2. Confirmation must apply to the current ride context.

3. Before requesting confirmation, the caller must have been given the
   important booking details required to make the decision.

4. These should include at minimum:

   - pickup
   - destination
   - requested time
   - selected vehicle
   - estimated total fare

5. Confirmation must represent clear intent to proceed with booking.

6. Vehicle selection alone is not confirmation.

7. Asking for a fare is not confirmation.

8. Asking for availability is not confirmation.

9. Ambiguous conversational acknowledgements must not automatically be
   interpreted as booking confirmation.

10. Examples such as "hmm", "acha", or conversational "theek hai" may be
    acknowledgements rather than authorization and must not independently
    bypass the explicit-confirmation requirement.

11. Clear booking statements such as "book it", "confirm the ride",
    or equivalent unambiguous Hindi/Hinglish expressions may represent
    explicit confirmation when made against the current presented
    booking context.

12. A material change after confirmation invalidates confirmation.

13. Material changes include at minimum:

    - pickup
    - destination
    - requested time
    - passenger count when it affects eligibility
    - vehicle
    - quote/fare
    - applied offer

14. After invalidation, the updated booking details must be presented
    and explicit confirmation obtained again.

15. Confirmation is consumed by the booking attempt for the corresponding
    ride context and must not authorize unrelated future bookings.

### Output / Decision

- not_confirmed
- confirmation_requested
- explicitly_confirmed
- confirmation_invalidated

### Failure / Edge Cases

- Ambiguous "theek hai"
- Caller changes time after confirming
- Caller changes destination after confirming
- Requote changes fare
- Caller says "yes" without having been presented a booking summary
- Caller confirms and immediately corrects something
- Duplicate confirmation after successful booking

### LLM Responsibilities

The LLM may:

- interpret natural-language confirmation intent,
- ask for confirmation naturally,
- summarize booking details.

The final permission to execute booking must still be enforced
deterministically by the booking service.

### LLM Must Not

The LLM must not:

- bypass confirmation,
- retain confirmation after material changes,
- interpret mere vehicle selection as booking authorization,
- reuse confirmation for another ride.

### Hard Invariants

- Explicit confirmation is mandatory.
- Confirmation belongs to a specific current ride context.
- Material changes invalidate previous confirmation.
- Changed fare requires the new estimate to be communicated before
  confirmation can authorize booking.

## 11. Ride Lifecycle Policy

### Purpose

Define valid ride states and prevent invalid ride-state transitions.

### Prototype States

- BOOKED
- ASSIGNED
- ON_TRIP
- COMPLETED
- CANCELLED

### Rules

1. A successfully created ride begins as BOOKED unless assignment occurs
   atomically as part of the booking workflow.

2. A BOOKED ride may transition to:

   - ASSIGNED
   - CANCELLED

3. An ASSIGNED ride may transition to:

   - ON_TRIP
   - CANCELLED

4. An ON_TRIP ride may transition to:

   - COMPLETED

5. COMPLETED is terminal.

6. CANCELLED is terminal.

7. Terminal rides must not return to an active state.

8. Invalid transitions must be rejected by deterministic domain logic.

9. The LLM must never directly alter ride status.

10. Every state change should have enough metadata for debugging and
    tracing.

11. Repeating an already-applied transition should be handled safely
    where idempotent behavior is appropriate.

### Output / Decision

- transition_allowed
- transition_rejected
- no_change

### Failure / Edge Cases

- Cancelling completed ride
- Completing booked ride without trip progression
- Starting cancelled ride
- Duplicate transition request
- Concurrent status updates
- Driver assignment failure

### LLM Responsibilities

The LLM may:

- understand requests such as ride status or cancellation,
- communicate the current status,
- invoke an appropriate service operation.

### LLM Must Not

The LLM must not:

- directly change ride status,
- invent ride status,
- override an invalid transition.

### Hard Invariants

- COMPLETED rides cannot transition again.
- CANCELLED rides cannot transition again.
- ON_TRIP cannot return to BOOKED or ASSIGNED.
- Invalid transitions are rejected regardless of LLM instruction.

### Cancellation Rules

12. Prototype v1 does not require an AT_PICKUP lifecycle state.

13. Cancellation is allowed while the ride is:

    - BOOKED
    - ASSIGNED

14. Cancellation is not supported after the ride has entered ON_TRIP.

15. Cancellation changes ride state to CANCELLED.

16. Cancellation must never delete the ride record.

17. Associated booking history, quote, locations, vehicle selection,
    timestamps, and other required audit information must be retained.

18. A successfully cancelled pre-trip ride has a final customer ride
    cost of zero for prototype v1.

19. Cancellation must not modify the historical booking quote.

20. If an ASSIGNED ride is cancelled, the associated driver must be
    released from that assignment.

21. A released driver may become eligible for other rides subject to
    Driver Availability Policy.

22. Driver simulation or movement associated with a cancelled ride must
    stop.

23. Dispatch must not assign or reassign a driver to a CANCELLED ride.

24. Cancellation operations must be idempotent.

25. Repeating cancellation for an already CANCELLED ride must not create
    additional side effects.

### Returning Caller Cancellation

26. A caller may contact BoloRide in a later call/session and request
    cancellation of an existing ride.

27. Cancellation lookup must use persisted ride data rather than previous
    conversational memory.

28. The returning caller must be verified using the automatically detected
    incoming phone number and the name associated with that customer record
    before persisted rides may be exposed or modified.

29. Only rides belonging to the identified caller may be considered.

30. Only currently cancellable rides should be returned as cancellation
    candidates.

31. If exactly one cancellable ride exists, the system may present that
    ride for cancellation confirmation.

32. If multiple cancellable rides exist, the caller must identify which
    ride they intend to cancel.

33. The LLM must not arbitrarily choose between multiple rides.

34. The selected ride should be summarized sufficiently for the caller
    to recognize it, for example using:

    - destination
    - scheduled/requested time
    - vehicle type

35. Cancellation requires explicit cancellation confirmation after the
    target ride has been resolved.

36. Booking confirmation and cancellation confirmation are separate
    authorizations.

37. A previous booking confirmation must never authorize cancellation.

38. After successful cancellation, the caller must be informed that the
    ride has been cancelled.

### Prototype Lifecycle

BOOKED
  -> ASSIGNED
  -> ON_TRIP
  -> COMPLETED

BOOKED
  -> CANCELLED

ASSIGNED
  -> CANCELLED

### Prototype Decisions

- AT_PICKUP: not required
- Cancellation before ON_TRIP: allowed
- Cancellation after ON_TRIP begins: not supported
- Cancellation deletes data: never
- Returning-call cancellation: supported
- Cancellation confirmation: required
- Driver assignment: performed after successful booking through
  DispatchService
- Prototype v1 does not implement payment collection, refund processing,
  or cancellation fees. `final_customer_cost = 0` represents the prototype
  ride-accounting outcome only.

## 12. Driver Availability Policy

### Purpose

Determine whether a driver is currently eligible to receive a ride.

Driver existence, driver availability, and driver eligibility are
separate concepts.

### Inputs

- Driver
- Driver active status
- Online/offline status
- Driver work schedule
- Current/requested time
- Driver capability
- Driver vehicle
- Vehicle type required by ride
- Current driver assignment
- Latest known driver location
- Ride type

### Rules

1. A driver must be active to receive a ride.

2. A driver must currently be online/available.

3. A driver must be within an enabled work schedule for the relevant time.

4. Driver working hours must be configurable rather than hardcoded.

5. A driver may support:

   - CITY
   - INTERCITY
   - BOTH

6. The requested ride must be compatible with the driver's capability.

7. The driver must have an active vehicle compatible with the selected
   vehicle type.

8. A driver already assigned to or performing another active ride must
   not receive another ride.

9. A driver must have a sufficiently recent known location to participate
   in proximity-based dispatch.

10. Driver location does not itself imply availability.

11. An available driver may remain stationary while idle.

12. Driver availability must be revalidated when assignment is attempted.

### Output / Decision

- eligible
- unavailable
- outside_schedule
- incompatible_capability
- incompatible_vehicle
- busy
- location_unavailable

### Failure / Edge Cases

- Driver goes offline during dispatch
- Driver schedule ends during selection
- Driver has no recent location
- Driver vehicle becomes inactive
- Driver is already assigned
- Driver supports city rides but request is intercity
- Multiple drivers become eligible simultaneously

### LLM Responsibilities

The LLM may:

- communicate that drivers are being checked,
- communicate availability results returned by services.

### LLM Must Not

The LLM must not:

- mark a driver available,
- modify a driver's schedule,
- override driver capability,
- override vehicle compatibility,
- select a driver,
- invent driver location.

### Hard Invariants

- Offline drivers cannot be assigned.
- Inactive drivers cannot be assigned.
- Busy drivers cannot be assigned.
- Incompatible drivers cannot be assigned.
- Driver availability must be revalidated at assignment time.

### Driver Location and Schedule Rules

13. Driver location is simulated for prototype v1.

14. The simulator should update an active moving driver's location
    approximately once per second.

15. Idle available drivers may remain stationary.

16. The application should consume driver-location state through an
    abstraction that can later be replaced by real GPS/location events.

17. Production design may receive near-real-time driver locations from
    driver devices using streaming, push events, webhooks, or another
    appropriate location transport.

18. Domain and dispatch logic must not depend on whether location came
    from the prototype simulator or a future real GPS source.

19. For prototype dispatch, the latest simulated location is sufficient
    when the simulator/driver is active and healthy.

20. Driver schedules are represented as configurable availability
    windows rather than hardcoded application hours.

21. A schedule should contain at minimum:

    - driver
    - day of week
    - start time
    - end time
    - enabled state

22. Schedule evaluation must use deterministic backend time logic.

23. A driver outside an enabled availability window is not eligible for
    assignment.

### Prototype Decisions

- Driver location source: simulator
- Active movement update interval: approximately 1 second
- Idle driver behavior: may remain stationary
- Future production location source: replaceable real-time GPS source
- Driver schedules: configurable day/time availability windows

## 13. Dispatch Policy

### Purpose

Select and assign an eligible driver to a confirmed ride.

### Inputs

- Ride
- Selected vehicle type
- Ride type
- Pickup coordinates
- Eligible drivers
- Driver locations
- Driver availability
- Existing assignments

### Rules

1. Dispatch occurs only for a successfully created ride requiring
   assignment.

2. DispatchService is responsible for driver selection.

3. The voice agent must never select a driver directly.

4. Candidate drivers must first pass Driver Availability Policy.

5. Candidates must have a compatible vehicle.

6. Candidates must not already have another active assignment.

7. Eligible candidates are ranked by proximity to the pickup.

8. For the prototype, straight-line (Haversine) distance may be used for
   initial ranking.

9. Maps routing is not required merely to rank every candidate.

10. The nearest eligible candidate is selected for the prototype.

11. Driver eligibility must be revalidated immediately before assignment.

12. Assignment must be concurrency-safe so the same driver cannot be
    assigned simultaneously to multiple rides.

13. Successful assignment transitions the ride from `BOOKED` to `ASSIGNED`.

14. The selected driver becomes unavailable for other assignments.

15. If the selected candidate becomes unavailable during assignment,
    dispatch may attempt the next eligible candidate.

16. If no eligible driver remains, the system must return an explicit
    no-driver-available outcome.

17. The system must never fabricate driver details.

18. For the prototype, driver acceptance or rejection is intentionally
    omitted.

19. The prototype automatically assigns the nearest eligible driver.

20. This auto-assignment behavior must be documented as a prototype
    simplification rather than production marketplace behavior.

21. Dispatch must re-check ride status immediately before committing
    driver assignment.

22. If the ride became CANCELLED while dispatch was executing, assignment
    must not be committed.

23. Cancellation and dispatch must be designed so that a race between
    them cannot leave a CANCELLED ride holding an active driver
    assignment.

24. Driver assignment occurs after successful ride booking.

25. Prototype dispatch automatically assigns the nearest eligible driver;
    driver acceptance or rejection is outside prototype v1.

### Output / Decision

- assigned
- no_driver_available
- retry_next_candidate
- dispatch_failed

Successful assignment should return at minimum:

- driver identifier
- driver display name
- vehicle registration
- vehicle information required for caller communication
- assignment status

### Failure / Edge Cases

- No eligible drivers
- Nearest driver becomes busy
- Concurrent booking attempts
- Missing/stale driver location
- Assignment persistence failure
- Ride cancelled while dispatch is running
- Duplicate dispatch request

### LLM Responsibilities

The LLM may:

- tell the caller that a driver is being assigned,
- communicate assigned driver/vehicle information returned by services.

### LLM Must Not

The LLM must not:

- calculate nearest driver,
- choose a driver,
- mark a driver assigned,
- invent driver/vehicle details,
- override dispatch failure.

### Hard Invariants

- Only eligible drivers may be assigned.
- One driver cannot serve two active rides simultaneously.
- CANCELLED rides cannot receive new driver assignments.
- Driver assignment must be performed by deterministic backend logic.

## 14. Session Lifecycle Policy

### Purpose

Control conversational session behavior so calls do not remain open
unnecessarily while still giving callers a reasonable opportunity to
continue or recover from silence.

### Inputs

- Current session state
- User speech activity
- Silence duration
- Consecutive silence-recovery count
- Active backend operation
- Backend operation duration
- Goal completion state
- User continuation/termination intent

### Rules

1. User silence and backend computation latency must be treated
   differently.

2. Silence timeout duration must be configurable.

3. Genuine user speech resets the consecutive silence-recovery counter.

4. After the first qualifying silence period, the agent may issue a
   short recovery prompt.

5. After a second qualifying silence period, the agent may issue one
   final recovery prompt.

6. If silence continues after two recovery prompts, the session should
   end politely.

7. Maximum consecutive silence-recovery prompts:

   2

8. The two recovery prompts should use different wording so the caller is not
   given the same recovery prompt twice unnecessarily.

9. A slow maps, pricing, dispatch, or booking operation must not be
   interpreted as user silence.

10. Backend operation latency should have a separate configurable
    progress-message threshold.

11. If a backend operation exceeds that threshold, the agent may provide
    a brief acknowledgement such as:

    "One moment, I'm checking available rides."

12. Short operations should not trigger unnecessary filler speech.

13. The agent must never wait indefinitely for either caller input or a
    backend operation.

14. After completing the caller's current goal, the agent should provide
    a reasonable opportunity for another request.

15. Example:

    "Do you need any more help?"

16. If the caller provides another supported request, the same session
    may continue with a new goal.

17. If the caller clearly indicates that no further assistance is
    required, the agent should close politely and disconnect.

18. If the caller becomes silent after goal completion, the normal
    silence-recovery policy applies.

19. Ending a voice session must not delete ride, quote, user, or other
    persisted business data.

### Output / Decision

- continue_listening
- issue_first_silence_prompt
- issue_final_silence_prompt
- provide_progress_acknowledgement
- continue_with_new_goal
- close_session

### Failure / Edge Cases

- Caller goes silent mid-booking
- Caller goes silent after successful booking
- Maps request is slow
- Booking operation is slow
- Caller interrupts a recovery prompt
- Speech resumes immediately before disconnect
- Caller starts a second request after completing the first

### LLM Responsibilities

The LLM may:

- generate natural recovery wording,
- generate concise progress acknowledgements,
- ask whether further assistance is needed,
- close the conversation naturally.

### LLM Must Not

The LLM must not:

- decide timeout durations,
- keep the call open indefinitely,
- confuse backend latency with caller silence,
- delete persisted business state when the call ends.

### Hard Invariants

- Maximum two consecutive silence-recovery prompts.
- Genuine user speech resets the silence-recovery counter.
- Backend computation time is not caller silence.
- Calls must not remain open indefinitely.
- Completed goals receive a reasonable opportunity for continuation.

## 15. Security Guardrail Policy

### Purpose

Detect and safely handle attempts to manipulate the agent outside its
permitted BoloRide responsibilities.

### Inputs

- Caller transcript/input
- Guardrail rules
- Session identifier
- Correlation/trace identifier
- Caller identifier where legitimately available
- Previous security events in the current session where required

### Rules

1. Security screening should occur before potentially unsafe instructions
   are acted upon by the main conversational agent.

2. High-confidence deterministic patterns may be intercepted before the
   normal LLM execution path.

3. Relevant categories may include attempts to:

   - override system/developer instructions,
   - request hidden/system prompts,
   - manipulate tool execution,
   - bypass booking or security rules,
   - impersonate privileged system instructions.

4. Detection should be narrowly scoped enough to reduce false positives.

5. Suspicious wording alone must not automatically result in permanent
   user punishment.

6. When an input is blocked, the normal LLM should not execute the
   prohibited instruction.

7. The system should return a fixed or tightly controlled safe response.

8. A security event should be recorded when a configured guardrail
   threshold is met.

9. Security event data should include only information required for
   investigation and traceability.

10. Security event records should include where available:

    - event ID
    - timestamp
    - call/session ID
    - trace/correlation ID
    - privacy-conscious caller identifier
    - violation type
    - matched rule
    - relevant evidence/input

11. Security events should be correlatable with application logs and
    observability traces.

12. A detected event must not automatically blacklist a caller.

13. Legitimate BoloRide requests containing words such as "system",
    "prompt", "ignore", or similar terms must not be blocked solely
    because an individual keyword appears.

### Output / Decision

- allow
- block_and_respond
- record_security_event
- terminate_session where separately justified by policy

### Failure / Edge Cases

- Legitimate sentence resembles an injection pattern
- Repeated injection attempts
- Mixed legitimate request and malicious instruction
- Guardrail subsystem fails
- Caller asks how BoloRide works
- Caller uses technical words innocently

### LLM Responsibilities

For blocked deterministic guardrail events, the main conversational LLM
should not be responsible for deciding whether its own instructions may
be overridden.

For allowed requests, normal conversational processing continues.

### LLM Must Not

The LLM must not:

- reveal protected system instructions,
- override deterministic business policies,
- authorize its own policy bypass,
- blacklist callers,
- claim that a human reviewed an event when no such review occurred.

### Hard Invariants

- Prompt instructions cannot override deterministic business rules.
- Automatic detection cannot permanently blacklist a caller.
- Blocked instructions must not be executed merely because the caller
  requests them.
- Security-event claims communicated to callers must reflect actions
  the system actually performs.

### Prototype Security Decisions

14. Prototype deterministic detection should focus on high-confidence
    manipulation attempts rather than broad keyword blocking.

15. Detection categories include:

    - explicit instruction-hierarchy override attempts,
    - explicit requests for hidden/system prompts,
    - explicit attempts to bypass booking confirmation,
    - explicit attempts to force unauthorized tool execution,
    - explicit attempts to manipulate internal security behavior.

16. Individual words such as "ignore", "prompt", "system", "tool",
    or "developer" are never sufficient by themselves to block input.

17. On the first blocked security event in a session, the system should:

    - record the event,
    - refuse the prohibited request,
    - redirect the caller toward supported BoloRide assistance.

18. On repeated high-confidence blocked attempts within the same session,
    the event count should be retained.

19. For prototype v1, after 3 high-confidence blocked security events in
    the same call/session, the system must politely terminate the session.

20. This termination does not blacklist the caller.

21. A future call from the same caller is independently permitted unless
    a human-reviewed persistent blacklist exists.

22. Security events should be retained for the prototype's internal
    debugging/review history.

23. Prototype v1 does not require automated deletion/retention expiry
    before the hackathon submission.

24. Caller-facing responses should not claim that a human is currently
    reviewing the event.

25. A suitable response may communicate:

    "Main sirf BoloRide se related requests mein madad kar sakta hoon."

26. The system may internally record the security event without
    announcing technical security classifications to the caller.

### Prototype Decisions

- Detection strategy: narrow/high-confidence deterministic rules
- Keyword-only blocking: prohibited
- First/second blocked attempt: refuse + redirect
- After the third high-confidence blocked security event within the same
  call/session, the system terminates the session politely.
- Automatic blacklist: never
- Security-event retention for prototype: retained for internal review
- Caller-facing "security review" claim: do not use

## 16. Human Review / Blacklist Policy

### Purpose

Ensure that restrictive actions against callers are based on deliberate
human review rather than automatic guardrail classification.

### Inputs

- Security events
- Event evidence
- Session/trace information
- Existing blacklist state
- Authorized reviewer decision

### Rules

1. Automated guardrail detection may create security events.

2. Automated guardrail detection must not permanently blacklist a caller.

3. Permanent blacklist decisions require explicit human review.

4. The reviewer should be able to inspect sufficient evidence to
   distinguish:

   - true policy abuse
   - false positive
   - misunderstood legitimate request

5. Blacklist status must be stored independently from individual
   security events.

6. Security-event existence does not itself imply blacklist status.

7. A blacklist action should record:

   - decision
   - reviewer/audit identifier
   - timestamp
   - reason
   - relevant security-event references

8. A caller must not be described as blacklisted unless persistent
   blacklist state actually indicates that status.

9. Blacklist checks, if enforced during call handling, must use persisted
   backend state rather than LLM memory.

10. The LLM must not add or remove callers from the blacklist.

### Output / Decision

Human review may result in:

- no_action
- confirmed_false_positive
- blacklist
- remove_existing_blacklist

### Failure / Edge Cases

- False-positive security event
- Multiple events from same caller
- Missing evidence
- Duplicate review
- Previously blacklisted caller
- Blacklist later determined to be incorrect

### LLM Responsibilities

The LLM may communicate only the caller-facing behavior explicitly
permitted by the application.

### LLM Must Not

The LLM must not:

- blacklist callers,
- remove blacklist status,
- impersonate a human reviewer,
- claim human review occurred when it did not.

### Hard Invariants

- Permanent blacklisting requires human action.
- Security-event detection alone cannot blacklist a caller.
- Blacklist state must be auditable.