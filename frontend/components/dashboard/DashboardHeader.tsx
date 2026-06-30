export default function DashboardHeader() {

  const hour = new Date().getHours();

  let greeting = "Good Evening";

  if(hour < 12){
    greeting = "Good Morning";
  }
  else if(hour < 18){
    greeting = "Good Afternoon";
  }

  return (

    <div className="mb-10">

      <h2 className="text-4xl font-bold">

        {greeting},

        <span className="ml-2 bg-gradient-to-r from-white via-slate-300 to-slate-500 bg-clip-text text-transparent">
          Investor 👋
        </span>

      </h2>

      <p className="mt-3 text-slate-400 text-lg">
        Here's what's happening in today's IPO market.
      </p>

    </div>

  );

}