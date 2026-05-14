def calculate_emergency_fund():
    expenses = []
    
    print("Enter your monthly expenses. Type 'done' when finished.\n")
    
    while True:
        name = input("Expense name: ")
        
        if name.lower() == 'done':
            break
        
        try:
            amount = float(input(f"Amount for {name}: "))
            expenses.append((name, amount))
        except ValueError:
            print("Please enter a valid number.\n")
    
    if not expenses:
        print("\nNo expenses entered.")
        return
    
    total = sum(amount for _, amount in expenses)
    
    print("\n--- Monthly Expenses ---")
    for name, amount in expenses:
        print(f"{name}: €{amount:.2f}")
    
    print("\n--- Summary ---")
    print(f"Total Monthly Spending: €{total:.2f}")
    print(f"Emergency Fund (1 month): €{total:.2f}")
    print(f"Emergency Fund (6 months): €{total * 6:.2f}")


# Run the script
calculate_emergency_fund()
