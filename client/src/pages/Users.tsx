import { useState } from "react";
import { Plus } from "lucide-react";
import { useIntl } from "react-intl";
import { Button } from "@/components/ui/button";
import { UserForm } from "@/components/users/UserForm";

export function Users() {
  const intl = useIntl();
  const [isFormOpen, setIsFormOpen] = useState(false);

  return (
    <div className="p-6">
      {isFormOpen ? (
        <UserForm
          isOpen={isFormOpen}
          onToggle={() => setIsFormOpen(false)}
          onSuccess={() => {
            setIsFormOpen(false);
            // TODO: Refresh users list when implemented
          }}
        />
      ) : (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">
              {intl.formatMessage({ id: "users.title" })}
            </h1>
            <Button onClick={() => setIsFormOpen(true)} className="gap-2">
              <Plus className="h-4 w-4" />
              {intl.formatMessage({ id: "users.createUser" })}
            </Button>
          </div>
          {/* TODO: Add users table/list here */}
        </div>
      )}
    </div>
  );
}
